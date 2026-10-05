from dataclasses import FrozenInstanceError
from unittest import TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.core.target_config import TargetConfig


class TestTargetConfig(TestCase):
    def test_defaults_preserve_automatic_scheme_and_no_override(self):
        config = TargetConfig()
        self.assertIsNone(config.default_scheme)
        self.assertIsNone(config.connect_host)
        self.assertFalse(config.proxy_configured)

    def test_options_adapter_uses_only_its_supplied_mapping(self):
        values = {
            "scheme": "https", "ip": "2001:db8::7",
            "proxies": [], "tor": False,
        }
        with patch.dict(options, {}, clear=True):
            config = TargetConfig.from_options(values)
        self.assertEqual(config, TargetConfig("https", "2001:db8::7", False))

    def test_snapshot_does_not_follow_input_mutations(self):
        values = {
            "scheme": "https", "ip": "192.0.2.7",
            "proxies": ["http://proxy.test:8080"], "tor": False,
        }
        config = TargetConfig.from_options(values)
        values["proxies"].clear()
        values.update(scheme="http", ip=None, tor=False)
        self.assertEqual(config, TargetConfig("https", "192.0.2.7", True))
        for name, value in (("default_scheme", "http"), ("connect_host", None), ("proxy_configured", False)):
            with self.subTest(name=name), self.assertRaises(FrozenInstanceError):
                setattr(config, name, value)

    def test_proxy_guard_keeps_existing_proxy_or_tor_semantics(self):
        for proxies, tor, expected in (
            ([], False, False), ([], None, False),
            (["http://proxy.test:8080"], False, True),
            (["socks5h://proxy.test:1080"], False, True),
            ([], True, True), (["http://proxy.test:8080"], True, True),
        ):
            with self.subTest(proxies=proxies, tor=tor):
                config = TargetConfig.from_options({
                    "scheme": None, "ip": None, "proxies": proxies, "tor": tor,
                })
                self.assertIs(config.proxy_configured, expected)

    def test_proxy_credentials_are_not_copied_into_target_policy(self):
        config = TargetConfig.from_options({
            "scheme": None, "ip": None,
            "proxies": ["http://user:secret@proxy.test:8080"], "tor": False,
        })
        self.assertTrue(config.proxy_configured)
        self.assertNotIn("user", repr(config))
        self.assertNotIn("secret", repr(config))
        self.assertNotIn("proxy.test", repr(config))
