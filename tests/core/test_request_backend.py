from types import SimpleNamespace
from unittest import TestCase

from lib.core.request_backend import get_native_request_backend_error


def native_options(**overrides):
    values = {
        "async_mode": False,
        "http_method": "GET",
        "data": None,
        "data_file": None,
        "proxies": [],
        "proxies_file": None,
        "tor": False,
        "proxy_auth": None,
        "replay_proxy": None,
        "auth": None,
        "auth_type": None,
        "cert_file": None,
        "key_file": None,
        "random_agents": False,
        "network_interface": None,
        "max_rate": 0,
        "delay": 0,
        "follow_redirects": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestRequestBackend(TestCase):
    def test_native_accepts_default_supported_options(self):
        self.assertIsNone(get_native_request_backend_error(native_options()))

    def test_native_rejects_async_mode(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(async_mode=True)),
            "--request-backend native cannot be combined with --async",
        )

    def test_native_rejects_non_get_methods(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(http_method="POST")),
            "--request-backend native currently supports GET requests only",
        )

    def test_native_rejects_proxies(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(proxies=["127.0.0.1:8080"])),
            "--request-backend native does not support proxies yet",
        )

    def test_native_rejects_delay(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(delay=0.1)),
            "--request-backend native does not support --delay yet",
        )
