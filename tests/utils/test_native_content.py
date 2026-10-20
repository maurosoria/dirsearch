import itertools
import random
import string
from unittest import TestCase, skipUnless
from unittest.mock import patch

from lib.utils import diff


NATIVE_AVAILABLE = diff._native_similarity is not None


class TestContentFallback(TestCase):
    def test_optional_extension_is_not_required(self):
        with patch.multiple(diff, _native_normalize_ascii=None, _native_similarity=None):
            self.assertEqual(diff.normalize_dynamic_content("token='value' 123456"), "__DYNAMIC_ATTR__ __DYNAMIC__")
            self.assertEqual(diff.normalized_content_similarity("tide", "diet"), 0.25)

    def test_unicode_normalization_keeps_python_semantics(self):
        samples = (
            "café\u0085token='abc'\u2003123456",
            "İSESSION_ID='value' ſession-id='other'",
            "\ud800 token='value' \udfff",
            "١٢٣٤٥٦ / 123456 / ＡＢＣＤ",
        )
        with patch.object(diff, "_native_normalize_ascii", side_effect=AssertionError("Unicode must use Python")):
            for sample in samples:
                self.assertEqual(diff.normalize_dynamic_content(sample), diff._normalize_dynamic_content_python(sample))


@skipUnless(NATIVE_AVAILABLE, "matching native extension not installed")
class TestNativeContent(TestCase):
    def assert_ratio(self, first, second):
        self.assertEqual(
            diff.normalized_content_similarity(first, second),
            diff._normalized_content_similarity_python(first, second),
            (repr(first[:60]), repr(second[:60]), len(first), len(second)),
        )

    def test_exhaustive_short_sequences_preserve_matching_block_ties(self):
        texts = ["".join(chars) for n in range(5) for chars in itertools.product("abc", repeat=n)]
        for first in texts:
            for second in texts:
                self.assert_ratio(first, second)

    def test_autojunk_boundaries_and_asymmetry(self):
        self.assert_ratio("tide", "diet")
        self.assert_ratio("diet", "tide")
        for length in (198, 199, 200, 201, 299, 300, 1000):
            for first, second in (
                ("a" * length, "b" + "a" * length),
                ("abc" * length, "a" + "abc" * length),
                ("ab" * length + "end", "ab" * length + "last"),
                ("x" + "a" * length + "y", "y" + "a" * length + "x"),
            ):
                self.assert_ratio(first, second)
                self.assert_ratio(second, first)

    def test_random_edits_unicode_and_repeated_blocks(self):
        rng = random.Random(20261020)
        alphabet = "abcd éñλ中🙂\u0301\x00\n"
        for _ in range(600):
            first = "".join(rng.choices(alphabet, k=rng.randrange(600)))
            start, end = sorted((rng.randrange(len(first) + 1), rng.randrange(len(first) + 1)))
            second = first[:start] + "".join(rng.choices(alphabet, k=rng.randrange(40))) + first[end:]
            self.assert_ratio(first, second)
            self.assert_ratio(second, first)

    def test_lone_surrogates_use_the_python_ratio(self):
        self.assert_ratio("a\ud800b", "a\ud800c")
        self.assert_ratio("\udfff" * 201, "\udfff" * 200)

    def test_long_sequences_with_many_unpopular_characters(self):
        rng = random.Random(20261021)
        alphabet = string.printable + "éλ中🙂"
        for _ in range(200):
            first = "".join(rng.choices(alphabet, k=rng.randrange(200, 2400)))
            start, end = sorted((rng.randrange(len(first)), rng.randrange(len(first))))
            second = first[:start] + "changed" + first[end:]
            self.assert_ratio(first, second)
            self.assert_ratio(second, first)

    def test_normalization_exact_replacement_order_and_whitespace(self):
        samples = [
            "", " \t\n\r\v\f\x1c\x1d\x1e\x1f ",
            "nonce='abc' request-id=\"value\" CSRF='other'",
            "trace=550e8400-e29b-41d4-a716-446655440000 id=0123456789abcdef",
            "x abcdefghijklmnopqrstuvwxyz== y/abcdefghijklmnopqrstuvwx/",
            "2026-10-20T03:12:00Z 10:12:34.56 123456 12345",
            "token='2026-10-20 123456 550e8400-e29b-41d4-a716-446655440000'",
            "prefix_token='a' csrf='one\"two' trace-id = 'untouched'",
        ]
        rng = random.Random(20261020)
        fragments = samples[2:] + [string.ascii_letters, string.digits, "\x00\x1c", "_", "/", "+", "="]
        samples.extend(" ".join(rng.choices(fragments, k=rng.randrange(1, 30))) for _ in range(500))
        for sample in samples:
            self.assertEqual(diff.normalize_dynamic_content(sample), diff._normalize_dynamic_content_python(sample), repr(sample))

    def test_parser_decisions_match_the_python_reference(self):
        profiles = (
            ("missing alpha stable template", "missing bravo stable template", "missing charlie stable template"),
            ('{"fields":"' + '"a":"missing",' * 80 + '","path":"/alpha"}',
             '{"fields":"' + '"a":"missing",' * 80 + '","path":"/bravo"}',
             '{"fields":"' + '"a":"missing",' * 80 + '","path":"/charlie"}'),
            ("abc " * 200 + "alpha", "abc " * 200 + "bravo", "abc " * 200 + "charlie"),
            ("", "", "valid content"),
        )
        for first, second, candidate in profiles:
            native = diff.DynamicContentParser(first, second)
            observed = (native.compare_to(candidate), native.similarity_to(candidate), native.is_ambiguous)
            with patch.multiple(diff, _native_normalize_ascii=None, _native_similarity=None):
                reference = diff.DynamicContentParser(first, second)
                expected = (reference.compare_to(candidate), reference.similarity_to(candidate), reference.is_ambiguous)
            self.assertEqual(observed, expected)
