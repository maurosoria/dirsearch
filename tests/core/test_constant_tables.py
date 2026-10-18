"""Shared lookup tables cannot become another invocation's mutable state."""

from unittest import TestCase

from lib.core.filters import SIZE_UNITS
from lib.core.settings import (
    DEFAULT_HEADERS,
    STANDARD_PORTS,
    TEXT_CHARS,
    WORDLIST_CATEGORIES,
)
from lib.core.wordlist_template import DEFAULT_PLACEHOLDERS
from lib.report.manager import output_handlers


class TestConstantTables(TestCase):
    def test_shared_mappings_reject_item_assignment(self):
        for name, table in (
            ("SIZE_UNITS", SIZE_UNITS),
            ("WORDLIST_CATEGORIES", WORDLIST_CATEGORIES),
            ("STANDARD_PORTS", STANDARD_PORTS),
            ("DEFAULT_HEADERS", DEFAULT_HEADERS),
            ("DEFAULT_PLACEHOLDERS", DEFAULT_PLACEHOLDERS),
            ("output_handlers", output_handlers),
        ):
            with self.subTest(table=name):
                key = next(iter(table))
                # Reassign the same value so even the red phase leaves no
                # changed global contents for subsequent tests.
                with self.assertRaises(TypeError):
                    table[key] = table[key]

    def test_placeholder_and_registry_containers_are_immutable(self):
        # A read-only outer mapping must not hide mutable lists of defaults.
        for token, values in DEFAULT_PLACEHOLDERS.items():
            with self.subTest(token=token):
                self.assertIsInstance(values, tuple)
                self.assertTrue(all(isinstance(value, str) for value in values))
        for format, handler in output_handlers.items():
            with self.subTest(format=format):
                self.assertIsInstance(handler, tuple)
                self.assertIsInstance(handler[-1], tuple)
                self.assertTrue(all(isinstance(key, str) for key in handler[-1]))

    def test_binary_detection_table_rejects_item_assignment(self):
        with self.assertRaises(TypeError):
            TEXT_CHARS[0] = TEXT_CHARS[0]
