from unittest import TestCase

from lib.core.fingerprint import fingerprint_headers, merge_fingerprints


class TestFingerprint(TestCase):
    def test_detects_cloudflare_headers(self):
        result = fingerprint_headers(
            {
                "server": "cloudflare",
                "cf-ray": "abc",
                "content-type": "text/html",
            }
        )

        self.assertEqual(result.provider, "cloudflare")
        self.assertGreaterEqual(result.confidence, 0.6)
        self.assertIn("header:cf-ray", result.signals)

    def test_detects_akamai_headers(self):
        result = fingerprint_headers(
            {
                "server": "AkamaiGHost",
                "x-akamai-transformed": "9 123 0 pmb=mRUM,1",
            }
        )

        self.assertEqual(result.provider, "akamai")
        self.assertGreaterEqual(result.confidence, 0.6)

    def test_detects_akamai_edge_headers(self):
        result = fingerprint_headers(
            {
                "aka-global-request-id-uxtime": "0.2a1dd517.1780788574.b27af30",
                "server-timing": 'ak_p; desc="1780788573972_399842602";dur=1',
            }
        )

        self.assertEqual(result.provider, "akamai")
        self.assertGreaterEqual(result.confidence, 0.6)

    def test_merge_preserves_behavior_tags(self):
        merged = merge_fingerprints(
            [fingerprint_headers({"server": "cloudflare"})],
            behavior_tags=("scanner_false_positive_burst",),
        )

        self.assertEqual(merged.provider, "cloudflare")
        self.assertIn("scanner_false_positive_burst", merged.behavior_tags)
