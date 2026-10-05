from dataclasses import FrozenInstanceError
from unittest import TestCase

from lib.core.terminal_config import TerminalConfig


class TestTerminalConfig(TestCase):
    def test_normalized_options_are_detached_from_mutable_collections(self):
        values = {
            "color": False, "quiet": True, "disable_cli": False,
            "verbose": True, "extensions": ["html"], "prefixes": ["api/"],
            "suffixes": ["~"], "http_method": "POST", "thread_count": 7,
        }
        config = TerminalConfig.from_options(values)
        for key in ("extensions", "prefixes", "suffixes"):
            values[key].clear()
        values.update(color=True, quiet=False, http_method="GET", thread_count=99)

        self.assertEqual(config, TerminalConfig(
            color=False, quiet=True, verbose=True,
            extensions=("html",), prefixes=("api/",), suffixes=("~",),
            method="POST", concurrency=7,
        ))

    def test_direct_construction_is_immutable_and_copies_sequences(self):
        extensions = ["json"]
        config = TerminalConfig(extensions=extensions)
        extensions.append("html")
        self.assertEqual(config.extensions, ("json",))
        with self.assertRaises(FrozenInstanceError):
            config.color = False
