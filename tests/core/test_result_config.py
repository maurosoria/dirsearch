from dataclasses import FrozenInstanceError
from unittest import TestCase

from lib.core.result_config import ResultConfig


class TestResultConfig(TestCase):
    def test_snapshot_is_immutable_and_detached_from_input(self):
        values = {
            "save_response": "responses", "save_response_jsonl": "responses.jsonl",
            "full_url": True, "replay_proxy": "http://proxy.example.test:8080",
        }
        config = ResultConfig.from_options(values)
        values.clear()
        self.assertEqual(config, ResultConfig(
            "responses", "responses.jsonl", True, "http://proxy.example.test:8080",
        ))
        with self.assertRaises(FrozenInstanceError):
            config.full_url = False

    def test_capture_requires_at_least_one_nonempty_destination(self):
        for directory, jsonl, expected in (
            (None, None, False), ("", "", False),
            ("responses", None, True), (None, "responses.jsonl", True),
            ("responses", "responses.jsonl", True),
        ):
            with self.subTest(directory=directory, jsonl=jsonl):
                self.assertIs(ResultConfig(directory, jsonl).capture_full_body, expected)

    def test_presentation_and_replay_alone_do_not_enable_body_capture(self):
        config = ResultConfig(full_url=True, replay_proxy="http://proxy.example.test:8080")
        self.assertFalse(config.capture_full_body)

    def test_repr_omits_replay_proxy_credentials(self):
        config = ResultConfig(replay_proxy="http://user:sample-password@proxy.example.test")
        self.assertNotIn("sample-password", repr(config))
        self.assertNotIn(config.replay_proxy, repr(config))
