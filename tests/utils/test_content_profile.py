"""Request adapters consume an immutable public snapshot of parser state."""
from dataclasses import FrozenInstanceError
from unittest import TestCase

from lib.utils.diff import DynamicContentParser


class TestContentProfile(TestCase):
    def test_snapshot_is_immutable_and_does_not_follow_later_calibration(self):
        parser = DynamicContentParser('site missing alpha', 'site missing bravo')
        profile = parser.comparison_profile
        self.assertEqual(profile.base_content, 'site missing alpha')
        self.assertEqual(profile.static_patterns, tuple(parser.static_patterns))
        with self.assertRaises(FrozenInstanceError):
            profile.is_static = True
        parser.add_sample('different template')
        self.assertEqual(len(profile.normalized_contents), 2)
        self.assertEqual(len(parser.comparison_profile.normalized_contents), 3)
        self.assertNotEqual(profile.static_patterns, parser.comparison_profile.static_patterns)
