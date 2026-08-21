from unittest import TestCase

from lib.core.fingerprint import (
    Confidence,
    Strength,
    HTTP_SIGNATURES,
    fingerprint_headers,
    fingerprint_response,
    merge_fingerprints,
)


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

# A provider present in two network buckets, so a CNAME and an IP can both point
# at it - exercising distinct-technique corroboration without any HTTP signal.
ACME_DATASET = {
    "categories": {
        "common": {"acme": ["acme-cdn.net"]},
        "cdn": {"acme": ["198.51.100.0/24"]},
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
        # cf-ray is a DEFINITIVE signal -> conclusive on its own.
        self.assertEqual(result.certainty, Confidence.CONFIRMED)
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
        self.assertEqual(result.certainty, Confidence.CONFIRMED)

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
        self.assertEqual(result.certainty, Confidence.NONE)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.matches, ())

    def test_detects_cookie_and_body_waf_signals(self):
        result = fingerprint_response(
            {"set-cookie": "datadome=abc; Path=/"},
            body="DataDome blocked this request.",
        )

        self.assertEqual(result.provider, "datadome")
        self.assertEqual(result.category, "waf")
        # A STRONG cookie corroborated by a WEAK brand-in-body mention -> LIKELY.
        self.assertEqual(result.certainty, Confidence.LIKELY)
        self.assertIn("cookie:datadome", result.signals)
        self.assertIn("body_marker:datadome", result.signals)

    def test_generic_aws_signals_do_not_corroborate_to_likely(self):
        # x-amzn-requestid (generic AWS) + a "request blocked" page must NOT add
        # up to a confident AWS WAF verdict on plain AWS infrastructure.
        result = fingerprint_response(
            {"x-amzn-requestid": "abc"},
            body="Request blocked.",
        )

        # Only the generic request-id maps to aws_waf, and a lone WEAK signal is
        # at most POSSIBLE (never the LIKELY a corroborating phrase would force).
        self.assertEqual(result.certainty, Confidence.POSSIBLE)

    def test_generator_behavior_tags_survive_in_result(self):
        result = fingerprint_headers(
            {"server": "cloudflare"},
            behavior_tags=(tag for tag in ("waf_challenge",)),
        )

        self.assertEqual(result.certainty, Confidence.CONFIRMED)
        self.assertEqual(result.behavior_tags, ("waf_challenge",))

    def test_provider_with_none_certainty_is_not_inflated_by_merge(self):
        from lib.core.fingerprint import FingerprintResult

        merged = merge_fingerprints(
            [FingerprintResult(provider="cloudflare", category="waf", certainty=Confidence.NONE)]
        )

        self.assertEqual(merged.certainty, Confidence.NONE)

    def test_detects_tls_certificate_signal(self):
        result = fingerprint_response(
            {},
            tls_cert={"issuer": "Cloudflare Inc ECC"},
        )

        self.assertEqual(result.provider, "cloudflare")
        self.assertEqual(result.category, "waf")
        # A lone STRONG signal (vendor name in the cert) is suggestive, not proof.
        self.assertEqual(result.certainty, Confidence.LIKELY)
        self.assertIn("tls_cert:cloudflare", result.signals)

    def test_single_strong_header_is_likely_not_confirmed(self):
        result = fingerprint_headers({"server": "cloudflare"})

        self.assertEqual(result.provider, "cloudflare")
        self.assertEqual(result.certainty, Confidence.LIKELY)

    def test_two_strong_techniques_are_confirmed(self):
        result = fingerprint_response(
            {"server": "cloudflare"},
            tls_cert={"issuer": "Cloudflare Inc ECC"},
        )

        self.assertEqual(result.provider, "cloudflare")
        self.assertEqual(result.certainty, Confidence.CONFIRMED)

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
                # A single WEAK network signal is the lowest positive tier.
                self.assertEqual(result.certainty, Confidence.POSSIBLE)
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
                self.assertEqual(result.certainty, Confidence.POSSIBLE)
                self.assertTrue(any(match.technique == "ip_cidr" for match in result.matches))

    def test_two_weak_techniques_upgrade_to_likely(self):
        result = fingerprint_response(
            {},
            dns_cnames=("edge.acme-cdn.net",),
            resolved_ips=("198.51.100.7",),
            dataset=ACME_DATASET,
        )

        self.assertEqual(result.provider, "acme")
        # CNAME (WEAK) + IP (WEAK) are two independent techniques -> LIKELY.
        self.assertEqual(result.certainty, Confidence.LIKELY)

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
                self.assertEqual(result.certainty, Confidence.NONE)
                self.assertEqual(result.matches, ())

    def test_denial_behavior_promotes_provider_one_tier(self):
        result = fingerprint_headers(
            {"server": "cloudflare"},
            behavior_tags=("waf_challenge",),
        )

        self.assertEqual(result.provider, "cloudflare")
        # LIKELY (lone STRONG header) bumped one tier by the active challenge.
        self.assertEqual(result.certainty, Confidence.CONFIRMED)
        self.assertIn("runtime denial behavior", result.reason)

    def test_benign_behavior_tag_does_not_promote(self):
        result = fingerprint_headers(
            {"server": "cloudflare"},
            behavior_tags=("scanner_false_positive_burst",),
        )

        self.assertEqual(result.provider, "cloudflare")
        self.assertEqual(result.certainty, Confidence.LIKELY)
        self.assertNotIn("runtime denial behavior", result.reason)

    def test_denial_tag_caps_promotion_at_one_tier(self):
        # A WEAK-only match (lone IP) promoted by denial reaches LIKELY, never
        # CONFIRMED: a runtime tag cannot fabricate certainty from thin evidence.
        result = fingerprint_response(
            {},
            resolved_ips=("1.1.1.1",),
            dataset=TEST_DATASET,
            behavior_tags=("waf_rate_limit",),
        )

        self.assertEqual(result.provider, "cloudflare")
        self.assertEqual(result.certainty, Confidence.LIKELY)

    def test_denial_behavior_without_provider_is_behavioral_only(self):
        result = fingerprint_response({}, behavior_tags=("waf_rate_limit",))

        self.assertIsNone(result.provider)
        self.assertEqual(result.certainty, Confidence.BEHAVIORAL_ONLY)
        self.assertIn("waf_rate_limit", result.reason)

    def test_non_denial_tag_without_provider_is_none(self):
        result = fingerprint_response({}, behavior_tags=("request_error",))

        self.assertIsNone(result.provider)
        self.assertEqual(result.certainty, Confidence.NONE)

    def test_reason_names_the_deciding_signal(self):
        result = fingerprint_headers({"cf-ray": "abc"})

        self.assertEqual(result.reason, "definitive signal header:cf-ray")

    def test_confidence_property_is_display_only_projection(self):
        confirmed = fingerprint_headers({"cf-ray": "abc"})
        likely = fingerprint_headers({"server": "cloudflare"})
        none = fingerprint_headers({"server": "nginx"})

        self.assertEqual(confirmed.confidence, 0.95)
        self.assertEqual(likely.confidence, 0.75)
        self.assertEqual(none.confidence, 0.0)
        # The display float tracks the ordinal certainty monotonically.
        self.assertGreater(confirmed.confidence, likely.confidence)

    def test_signatures_use_discrete_strengths_not_floats(self):
        for signature in HTTP_SIGNATURES:
            for technique in ("headers", "cookies", "body_markers", "tls_cert"):
                for entry in signature.get(technique, ()):
                    strength = entry[-1]
                    with self.subTest(provider=signature["provider"], entry=entry):
                        self.assertIsInstance(strength, Strength)

    def test_merge_preserves_behavior_tags(self):
        merged = merge_fingerprints(
            [fingerprint_headers({"server": "cloudflare"})],
            behavior_tags=("scanner_false_positive_burst",),
        )

        self.assertEqual(merged.provider, "cloudflare")
        self.assertEqual(merged.category, "waf")
        self.assertEqual(merged.certainty, Confidence.LIKELY)
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
