from unittest import TestCase

from lib.connection import proxy as proxy_utils
from lib.connection.proxy import (
    format_proxy_error,
    is_proxy_connect_rejection,
    proxy_error_status,
)


class TestProxyErrors(TestCase):
    def test_proxy_authentication_encodes_userinfo_components(self):
        cases = (
            (
                "http://proxy.example:8080",
                "proxy/user:p@ss/word?#%:tail",
                "http://proxy%2Fuser:p%40ss%2Fword%3F%23%25%3Atail"
                "@proxy.example:8080",
            ),
            (
                "socks5://proxy.example:1080",
                "user name:password value",
                "socks5://user%20name:password%20value@proxy.example:1080",
            ),
            (
                "http://proxy.example:8080",
                "user%name",
                "http://user%25name@proxy.example:8080",
            ),
        )

        for proxy, credential, expected in cases:
            with self.subTest(credential=credential):
                self.assertEqual(
                    proxy_utils.add_proxy_authentication(proxy, credential),
                    expected,
                )

    def test_explicit_proxy_userinfo_takes_precedence(self):
        proxy = "http://inline-user:inline-password@proxy.example:8080"

        self.assertEqual(
            proxy_utils.add_proxy_authentication(proxy, "configured:credential"),
            proxy,
        )

    def test_at_sign_outside_proxy_authority_does_not_suppress_authentication(self):
        cases = (
            "http://proxy.example:8080/path@marker",
            "http://proxy.example:8080?tag=@marker",
        )

        for proxy in cases:
            with self.subTest(proxy=proxy):
                self.assertEqual(
                    proxy_utils.add_proxy_authentication(proxy, "user:password"),
                    proxy.replace("://", "://user:password@", 1),
                )

    def test_extracts_status_from_connect_failure(self):
        error = RuntimeError("Tunnel connection failed: 429 Too Many Requests")

        self.assertEqual(proxy_error_status(error), 429)
        self.assertEqual(
            format_proxy_error(error),
            "Proxy connection failed with HTTP 429",
        )

    def test_extracts_status_from_nested_bare_status(self):
        cause = RuntimeError("407 Proxy Authentication Required")
        error = RuntimeError("proxy connection failed")
        error.__cause__ = cause

        self.assertEqual(proxy_error_status(error), 407)
        self.assertEqual(format_proxy_error(error), "Proxy authentication required")

    def test_does_not_treat_url_numbers_as_http_status(self):
        error = "error sending request for url (http://127.0.0.1:429/path/500)"

        self.assertIsNone(proxy_error_status(error))
        self.assertEqual(
            format_proxy_error(error),
            "Cannot establish the proxy connection",
        )

    def test_formats_connect_rejection_when_client_discards_status(self):
        error = "client error (Connect): tunnel error: unsuccessful"

        self.assertTrue(is_proxy_connect_rejection(error))
        self.assertEqual(
            format_proxy_error(error),
            "Proxy CONNECT request was rejected",
        )
