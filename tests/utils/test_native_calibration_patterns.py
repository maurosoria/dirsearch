import difflib
import random
from unittest import TestCase, skipUnless
from unittest.mock import patch

from lib.utils import diff


@skipUnless(diff._native_similarity is not None, 'matching native extension unavailable')
class TestNativeCalibrationPatterns(TestCase):
    def test_supported_runtime_uses_native_patterns_for_ascii_samples(self):
        # This must run whenever the matching extension is installed. Skipping
        # on the pattern function itself would hide a new Python minor losing
        # the native path while the rest of the extension still works.
        with patch.object(difflib.Differ, 'compare', side_effect=AssertionError('unexpected Python pattern fallback')):
            parser = diff.DynamicContentParser('resource /alpha not found', 'resource /bravo not found')
        self.assertEqual(parser.static_patterns, ['resource', 'not', 'found'])

    def assert_patterns(self, first, second):
        expected = diff.DynamicContentParser.get_static_patterns(difflib.Differ().compare(first.split(), second.split()))
        self.assertEqual(diff._native_static_patterns(first, second), expected, (first[:80], second[:80]))

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
        actual = diff.DynamicContentParser(first, second)
        with patch.object(diff, '_native_static_patterns', None):
            expected = diff.DynamicContentParser(first, second)
        self.assertEqual(actual.static_patterns, expected.static_patterns)
        candidate = 'resource /charlie not found\n' * 210
        self.assertEqual(actual.compare_to(candidate), expected.compare_to(candidate))


class TestCalibrationProbeReuse(TestCase):
    def test_prefetched_first_probe_does_not_issue_a_duplicate_request(self):
        from lib.connection.response import NativeResponse
        from lib.core.filter_config import FilterConfig
        from lib.core.scanner import Scanner
        from lib.core.settings import WILDCARD_TEST_POINT_MARKER

        class Requester:
            def __init__(self):
                self.paths = []

            def request(self, path):
                self.paths.append(path)
                return NativeResponse('http://example.invalid/' + path, 404, [], b'missing')

        requester = Requester()
        first = NativeResponse('http://example.invalid/first', 404, [], b'missing')
        scanner = Scanner(requester, filter_config=FilterConfig(), delay=0,
                          path=WILDCARD_TEST_POINT_MARKER, first_probe=('first', first))
        self.assertEqual(scanner.sample_count, 2)
        self.assertEqual(len(requester.paths), 1)
        self.assertNotIn('first', requester.paths)
