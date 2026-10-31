import difflib
import random
import sys
from unittest import TestCase, skipUnless
from unittest.mock import patch

from lib.utils import diff
from lib.native import supports_native_differ


NATIVE_HELPERS = diff._get_native_content_helpers()


class TestNativeDifferVersions(TestCase):
    def test_only_verified_python_minors_replace_differ(self):
        for version in ((3, 14, 0), (3, 14, 10), (3, 15, 0)):
            self.assertTrue(supports_native_differ(version), version)
        for version in ((3, 13, 0), (3, 16, 0), (3, 99, 0), (4, 0, 0)):
            self.assertFalse(supports_native_differ(version), version)

    @skipUnless(NATIVE_HELPERS is not None, 'matching native extension unavailable')
    def test_unverified_policy_uses_python_differ_after_native_normalization(self):
        original_compare = difflib.Differ.compare
        with patch.object(diff, 'supports_native_differ', return_value=False):
            diff._get_native_content_helpers.cache_clear()
            try:
                with patch.object(difflib.Differ, 'compare', autospec=True, side_effect=original_compare) as compare:
                    parser = diff.DynamicContentParser(
                        'resource /alpha not found', 'resource /bravo not found', use_native=True,
                    )
                self.assertEqual(parser.static_patterns, ['resource', 'not', 'found'])
                compare.assert_called_once()
            finally:
                diff._get_native_content_helpers.cache_clear()


@skipUnless(NATIVE_HELPERS is not None and supports_native_differ(sys.version_info),
            'matching extension and verified Differ policy required')
class TestNativeCalibrationPatterns(TestCase):
    def test_supported_runtime_uses_native_patterns_for_ascii_samples(self):
        # A verified runtime must use native patterns when its extension matches.
        with patch.object(difflib.Differ, 'compare', side_effect=AssertionError('unexpected Python pattern fallback')):
            parser = diff.DynamicContentParser('resource /alpha not found', 'resource /bravo not found', use_native=True)
        self.assertEqual(parser.static_patterns, ['resource', 'not', 'found'])

    def assert_patterns(self, first, second):
        expected = diff.DynamicContentParser.get_static_patterns(difflib.Differ().compare(first.split(), second.split()))
        self.assertEqual(NATIVE_HELPERS.static_patterns(first, second), expected, (first[:80], second[:80]))

    def test_replacement_windows_and_autojunk_match_differ(self):
        rng = random.Random(20261023)
        vocabulary = ['a', 'b', 'c', 'abc', 'abd', 'alpha', 'bravo', 'missing', '/path', 'section']
        for _ in range(800):
            first = ' '.join(rng.choices(vocabulary, k=rng.randrange(50)))
            second = ' '.join(rng.choices(vocabulary, k=rng.randrange(50)))
            self.assert_patterns(first, second)
        for _ in range(120):
            first = ' '.join(rng.choices(vocabulary, k=rng.randrange(198, 450)))
            second = ' '.join(rng.choices(vocabulary, k=rng.randrange(198, 450)))
            self.assert_patterns(first, second)

    def test_repeated_reflected_paths_keep_exact_patterns(self):
        first = 'resource /alpha not found\n' * 250
        second = 'resource /bravo not found\n' * 250
        self.assert_patterns(first, second)
        self.assert_patterns(second, first)

    def test_parser_recalculation_keeps_python_patterns_and_decisions(self):
        first = 'resource /alpha not found\n' * 210
        second = 'resource /bravo not found\n' * 210
        actual = diff.DynamicContentParser(first, second, use_native=True)
        expected = diff.DynamicContentParser(first, second)
        self.assertEqual(actual.static_patterns, expected.static_patterns)
        candidate = 'resource /charlie not found\n' * 210
        self.assertEqual(actual.compare_to(candidate), expected.compare_to(candidate))
