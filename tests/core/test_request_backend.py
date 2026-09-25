from types import SimpleNamespace
from unittest import TestCase

from lib.core.request_backend import (
    get_async_request_backend_error,
    get_native_request_backend_error,
)


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
        "ip": None,
        "max_rate": 0,
        "delay": 0,
        "follow_redirects": False,
        "urls": ["https://example.com"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestRequestBackend(TestCase):
    def test_async_accepts_http_and_socks5_proxies(self):
        for proxy in (
            "http://127.0.0.1:8080",
            "https://127.0.0.1:8080",
            "socks5://127.0.0.1:1080",
            "socks5h://127.0.0.1:1080",
        ):
            with self.subTest(proxy=proxy):
                self.assertIsNone(
                    get_async_request_backend_error(
                        native_options(async_mode=True, proxies=[proxy])
                    )
                )

    def test_async_rejects_socks4_proxies(self):
        for scheme in ("socks4", "socks4a"):
            with self.subTest(scheme=scheme):
                self.assertEqual(
                    get_async_request_backend_error(
                        native_options(
                            async_mode=True,
                            proxies=[f"{scheme}://127.0.0.1:1080"],
                        )
                    ),
                    "--async supports SOCKS5 proxies only; use the threaded "
                    "engine for SOCKS4",
                )

    def test_threaded_backend_keeps_socks4_support(self):
        self.assertIsNone(
            get_async_request_backend_error(
                native_options(
                    async_mode=False,
                    proxies=["socks4://127.0.0.1:1080"],
                )
            )
        )

    def test_native_accepts_default_supported_options(self):
        self.assertIsNone(get_native_request_backend_error(native_options()))

    def test_native_rejects_async_mode(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(async_mode=True)),
            "--request-backend native cannot be combined with --async",
        )

    def test_native_accepts_http_methods_and_request_bodies(self):
        cases = (
            {"http_method": "POST", "data": "name=value"},
            {"http_method": "PATCH", "data": b"value=\xff\r\n"},
            {"http_method": "DELETE"},
            {"http_method": "PUT", "data_file": "request-body.bin"},
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.assertIsNone(
                    get_native_request_backend_error(native_options(**overrides))
                )

    def test_native_accepts_http_proxies(self):
        self.assertIsNone(
            get_native_request_backend_error(
                native_options(proxies=["127.0.0.1:8080", "https://proxy.example"])
            )
        )

    def test_native_accepts_proxy_authentication(self):
        self.assertIsNone(
            get_native_request_backend_error(
                native_options(
                    proxies=["127.0.0.1:8080"],
                    proxy_auth="user:password",
                )
            )
        )

    def test_native_rejects_socks_proxies(self):
        self.assertEqual(
            get_native_request_backend_error(
                native_options(proxies=["socks5://127.0.0.1:1080"])
            ),
            "--request-backend native supports HTTP and HTTPS proxies only",
        )

    def test_native_rejects_tor(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(tor=True)),
            "--request-backend native does not support Tor or SOCKS proxies yet",
        )

    def test_native_rejects_ip_override(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(ip="127.0.0.1")),
            "--request-backend native does not support --ip yet",
        )

    def test_native_accepts_replay_proxy(self):
        self.assertIsNone(
            get_native_request_backend_error(
                native_options(replay_proxy="http://127.0.0.1:8080")
            )
        )

    def test_native_rejects_embedded_target_credentials(self):
        self.assertEqual(
            get_native_request_backend_error(
                native_options(urls=["https://user:pass@example.com"])
            ),
            "--request-backend native does not support credentials embedded "
            "in target URLs yet",
        )

    def test_native_rejects_embedded_target_credentials_without_scheme(self):
        self.assertEqual(
            get_native_request_backend_error(
                native_options(urls=["user:pass@example.com"])
            ),
            "--request-backend native does not support credentials embedded "
            "in target URLs yet",
        )

    def test_native_accepts_follow_redirects(self):
        self.assertIsNone(
            get_native_request_backend_error(
                native_options(follow_redirects=True)
            )
        )

    def test_native_rejects_delay(self):
        self.assertEqual(
            get_native_request_backend_error(native_options(delay=0.1)),
            "--request-backend native does not support --delay yet",
        )
