from unittest import TestCase

from lib.core.fingerprint import fingerprint_headers, fingerprint_response, merge_fingerprints


TEST_DATASET = {
    "categories": {
        "common": {
            "amazon": ["cloudfront.net"],
            "akamai": ["edgekey.net"],
            "incapsula": ["impervadns.net"],
            "bad-provider": "not-a-list",
        },
        "cdn": {
            "cloudfront": ["23.228.249.0/24"],
            "broken": ["not-a-cidr"],
        },
        "waf": {
            "cloudflare": ["1.1.1.0/24"],
            "broken": "not-a-list",
        },
    }
}


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
        self.assertEqual(result.category, "waf")
        self.assertGreaterEqual(result.confidence, 0.6)
        self.assertIn("header:cf-ray", result.signals)
        self.assertTrue(result.matches)

    def test_detects_akamai_headers(self):
        result = fingerprint_headers(
            {
                "server": "AkamaiGHost",
                "x-akamai-transformed": "9 123 0 pmb=mRUM,1",
            }
        )

        self.assertEqual(result.provider, "akamai")
        self.assertEqual(result.category, "cdn")
        self.assertGreaterEqual(result.confidence, 0.6)

    def test_benign_headers_do_not_create_provider(self):
        result = fingerprint_headers(
            {
                "server": "nginx",
                "content-type": "text/html",
                "x-request-id": "abc",
            }
        )

        self.assertIsNone(result.provider)
        self.assertIsNone(result.category)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.matches, ())

    def test_detects_cookie_and_body_waf_signals(self):
        result = fingerprint_response(
            {"set-cookie": "datadome=abc; Path=/"},
            body="DataDome blocked this request.",
        )

        self.assertEqual(result.provider, "datadome")
        self.assertEqual(result.category, "waf")
        self.assertIn("cookie:datadome", result.signals)
        self.assertIn("body_marker:datadome", result.signals)

    def test_detects_tls_certificate_signal(self):
        result = fingerprint_response(
            {},
            tls_cert={"issuer": "Cloudflare Inc ECC"},
        )

        self.assertEqual(result.provider, "cloudflare")
        self.assertEqual(result.category, "waf")
        self.assertIn("tls_cert:cloudflare", result.signals)

    def test_detects_cname_suffixes_from_injected_dataset(self):
        cases = (
            ("d111111abcdef8.cloudfront.net.", "amazon"),
            ("www.example.edgekey.net", "akamai"),
            ("protected.impervadns.net", "incapsula"),
        )

        for cname, provider in cases:
            with self.subTest(cname=cname):
                result = fingerprint_response(
                    {},
                    dns_cnames=(cname,),
                    dataset=TEST_DATASET,
                )
                self.assertEqual(result.provider, provider)
                self.assertEqual(result.category, "common")
                self.assertTrue(
                    any(match.technique == "cname_suffix" for match in result.matches)
                )

    def test_detects_ip_cidrs_from_injected_dataset(self):
        cases = (
            ("1.1.1.1", "cloudflare", "waf"),
            ("23.228.249.1", "cloudfront", "cdn"),
        )

        for ip, provider, category in cases:
            with self.subTest(ip=ip):
                result = fingerprint_response(
                    {},
                    resolved_ips=(ip,),
                    dataset=TEST_DATASET,
                )
                self.assertEqual(result.provider, provider)
                self.assertEqual(result.category, category)
                self.assertTrue(any(match.technique == "ip_cidr" for match in result.matches))

    def test_http_signal_wins_over_generic_cidr(self):
        result = fingerprint_response(
            {"server": "cloudflare"},
            resolved_ips=("23.228.249.1",),
            dataset=TEST_DATASET,
        )

        self.assertEqual(result.provider, "cloudflare")
        self.assertEqual(result.category, "waf")
        self.assertIn("ip_cidr:23.228.249.0/24", result.signals)

    def test_missing_or_malformed_dataset_does_not_match_network_signals(self):
        malformed = {"categories": {"common": [], "cdn": [], "waf": []}}

        for dataset in (None, malformed):
            with self.subTest(dataset=dataset):
                result = fingerprint_response(
                    {},
                    dns_cnames=("d111111abcdef8.cloudfront.net.",),
                    resolved_ips=("1.1.1.1",),
                    dataset=dataset,
                )
                self.assertIsNone(result.provider)
                self.assertEqual(result.matches, ())

    def test_merge_preserves_behavior_tags(self):
        merged = merge_fingerprints(
            [fingerprint_headers({"server": "cloudflare"})],
            behavior_tags=("scanner_false_positive_burst",),
        )

        self.assertEqual(merged.provider, "cloudflare")
        self.assertEqual(merged.category, "waf")
        self.assertIn("scanner_false_positive_burst", merged.behavior_tags)

    def test_merge_preserves_matches(self):
        merged = merge_fingerprints(
            [
                fingerprint_response({"server": "cloudflare"}),
                fingerprint_response(
                    {},
                    dns_cnames=("site.cloudfront.net",),
                    dataset=TEST_DATASET,
                ),
            ],
            behavior_tags=("waf_challenge",),
        )

        self.assertEqual(merged.provider, "cloudflare")
        self.assertEqual(merged.category, "waf")
        self.assertIn("waf_challenge", merged.behavior_tags)
        self.assertTrue(any(match.provider == "amazon" for match in merged.matches))
