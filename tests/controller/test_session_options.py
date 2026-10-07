"""Persistence input is opaque, lossless and independent of runtime handles."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from unittest import TestCase

from lib.controller.session_options import SessionOptions


class TestSessionOptions(TestCase):
    def test_nested_input_and_every_export_are_independent(self):
        source = {
            "headers": {"Authorization": "Bearer private-value"},
            "proxies": ["http://proxy.test/"], "include_status_codes": {200},
            "extensions": ("html",), "data": b"\x80\r\n",
            "extra_option": {"nested": [1, {"value": "original"}]},
        }
        expected = deepcopy(source)
        captured = SessionOptions(source)
        source["headers"].clear()
        source["proxies"].clear()
        source["include_status_codes"].add(404)
        source["extra_option"]["nested"][1]["value"] = "changed"
        first = captured.to_options()
        self.assertEqual(first, expected)
        first["headers"].clear()
        first["proxies"].append("http://other.test/")
        first["include_status_codes"].clear()
        first["extra_option"]["nested"].clear()
        self.assertEqual(captured.to_options(), expected)
        self.assertEqual(captured, SessionOptions(expected))

    def test_empty_absent_null_and_unknown_values_are_not_defaulted(self):
        for values in ({}, {"auth": None}, {"headers": {}}, {"unknown": [None, "café", 0, False]}):
            with self.subTest(values=values):
                captured = SessionOptions(values)
                self.assertEqual(captured.to_options(), values)
        self.assertNotEqual(SessionOptions(), SessionOptions({"auth": None}))
        self.assertEqual(SessionOptions().to_options(), {})

    def test_capture_projects_target_input_but_direct_construction_rejects_it(self):
        values = {"urls": ["http://user:private-value@example.test/"], "headers": {"X-Test": "yes"}}
        captured = SessionOptions.from_options(values)
        self.assertEqual(captured.to_options(), {"headers": {"X-Test": "yes"}})
        self.assertIn("urls", values)
        for urls in (None, [], ["target"]):
            with self.subTest(urls=urls), self.assertRaisesRegex(ValueError, "remaining_tasks"):
                SessionOptions({"urls": urls})

    def test_overwrite_choice_is_a_new_value_without_changing_saved_snapshots(self):
        original = SessionOptions({"session_file": "existing", "headers": {"X-Test": "yes"}})
        for path in (None, "new", "existing"):
            with self.subTest(path=path):
                changed = original.with_session_file(path)
                self.assertIsNot(changed, original)
                self.assertEqual(changed.to_options(), {"session_file": path, "headers": {"X-Test": "yes"}})
                exported = changed.to_options()
                exported["headers"].clear()
                self.assertEqual(original.to_options(), {"session_file": "existing", "headers": {"X-Test": "yes"}})
        self.assertEqual(SessionOptions().with_session_file(None).to_options(), {"session_file": None})

    def test_no_mapping_protocol_or_secret_bearing_repr(self):
        captured = SessionOptions({"auth": "user:private-value", "data": "private-body"})
        self.assertEqual(repr(captured), "SessionOptions()")
        with self.assertRaises(TypeError):
            captured["auth"] = "changed"
        with self.assertRaises(TypeError):
            captured["auth"]
        with self.assertRaises(TypeError):
            dict(captured)
        with self.assertRaises(FrozenInstanceError):
            captured._values = {}

    def test_non_mappings_are_rejected_without_echoing_values(self):
        for value in ([], [("auth", "private-value")], "private-value", 1):
            with self.subTest(type=type(value)), self.assertRaisesRegex(
                TypeError, "^SessionOptions input must be a mapping$"
            ):
                SessionOptions(value)

    def test_deepcopy_preserves_the_value_contract(self):
        captured = SessionOptions({"headers": {"X-Test": "yes"}})
        copied = deepcopy(captured)
        exported = copied.to_options()
        exported["headers"].clear()
        self.assertEqual(copied, captured)
