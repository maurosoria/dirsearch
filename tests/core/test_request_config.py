from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from unittest import TestCase

from lib.core.data import options
from lib.core.request_config import RequestConfig


class TestRequestConfig(TestCase):
    def test_snapshot_detaches_headers_proxies_and_body(self):
        values = deepcopy(options)
        values.update(
            headers={"X-Run": "first"},
            proxies=["http://proxy.example:8080"],
            data=bytearray(b"first body"),
        )
        config = RequestConfig.from_options(values)
        values["headers"]["X-Run"] = "second"
        values["proxies"].append("http://other.example:8080")
        values["data"][:] = b"second body"
        values["timeout"] = 99

        self.assertEqual(config.headers, (("X-Run", "first"),))
        self.assertEqual(config.proxies, ("http://proxy.example:8080",))
        self.assertEqual(config.body, b"first body")
        self.assertNotEqual(config.timeout, 99)
        with self.assertRaises(FrozenInstanceError):
            config.timeout = 99
        with self.assertRaises(TypeError):
            config.headers[0] = ("X-Run", "second")

    def test_direct_construction_also_detaches_nested_lists(self):
        headers = [["X-Run", "first"]]
        proxies = ["http://proxy.example:8080"]
        body = bytearray(b"first")
        config = RequestConfig(headers=headers, proxies=proxies, body=body)
        headers[0][1] = "second"
        proxies.clear()
        body[:] = b"second"

        self.assertEqual(config.headers, (("X-Run", "first"),))
        self.assertEqual(config.proxies, ("http://proxy.example:8080",))
        self.assertEqual(config.body, b"first")

    def test_body_preserves_text_binary_and_empty_values(self):
        for body in (None, "", b"", "value=é\r\n", b"\x00\xff\r\n"):
            with self.subTest(body=body):
                config = RequestConfig(body=body)
                self.assertEqual(config.body, body)
                self.assertIs(type(config.body), type(body))

    def test_options_adapter_keeps_transport_fields(self):
        values = deepcopy(options)
        values.update(
            http_method="PATCH", data=b"data", headers={"X-Run": "first"},
            auth_type="digest", auth="user:password",
            proxies=["https://proxy.example:8443"], proxy_auth="proxy:password",
            cert_file="client.pem", key_file="client.key", network_interface="lo",
            random_agents=True, follow_redirects=True, thread_count=7,
            timeout=1.5, max_retries=2, max_rate=3, delay=0.25,
            save_response=None, save_response_jsonl="responses.jsonl",
        )

        self.assertEqual(
            RequestConfig.from_options(values),
            RequestConfig(
                method="PATCH", body=b"data", headers=(("X-Run", "first"),),
                auth_type="digest", auth="user:password",
                proxies=("https://proxy.example:8443",), proxy_auth="proxy:password",
                cert_file="client.pem", key_file="client.key", network_interface="lo",
                random_agents=True, follow_redirects=True, concurrency=7,
                timeout=1.5, max_retries=2, max_rate=3, delay=0.25,
                capture_full_body=True,
            ),
        )

    def test_capture_policy_does_not_include_output_destinations(self):
        values = deepcopy(options)
        for directory, jsonl, expected in (
            (None, None, False),
            ("responses", None, True),
            (None, "responses.jsonl", True),
            ("responses", "responses.jsonl", True),
        ):
            with self.subTest(directory=directory, jsonl=jsonl):
                values.update(save_response=directory, save_response_jsonl=jsonl)
                config = RequestConfig.from_options(values)
                self.assertIs(config.capture_full_body, expected)

    def test_replacement_leaves_the_original_snapshot_unchanged(self):
        original = RequestConfig(timeout=1, headers=(("X-Run", "first"),))
        replacement = replace(original, timeout=2)
        self.assertEqual(original.timeout, 1)
        self.assertEqual(replacement.timeout, 2)
        self.assertEqual(replacement.headers, original.headers)

    def test_repr_does_not_expose_request_secrets(self):
        config = RequestConfig(
            body="body-secret",
            headers=(("Authorization", "header-secret"),),
            auth="auth-secret",
            proxy_auth="proxy-secret",
            proxies=("http://user:url-secret@proxy.example",),
            key_file="key-secret",
        )
        rendered = repr(config)
        for value in (
            "body-secret", "header-secret", "auth-secret", "proxy-secret",
            "url-secret", "key-secret",
        ):
            self.assertNotIn(value, rendered)
