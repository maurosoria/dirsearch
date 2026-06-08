import os
import subprocess
import sys
from unittest import TestCase

from lib.connection.response import NativeResponse
from lib.core.runtime_fingerprint import (
    RUNTIME_MATCH_STREAK_THRESHOLD,
    DisabledRuntimeFilter,
    PreflightRuntimeFilter,
    build_runtime_filter,
    repeated_match_recalibration,
    response_fingerprint,
)


def runtime_response(path, body, *, status=200, headers=None):
    response_headers = {"content-type": "text/html"}
    response_headers.update(headers or {})
    return NativeResponse(
        f"https://example.com/{path}",
        status,
        list(response_headers.items()),
        body,
    )


class TestRuntimeFingerprint(TestCase):
    def test_build_runtime_filter_returns_disabled_filter_by_default(self):
        runtime_filter = build_runtime_filter(False)
        sample = runtime_response("block", b"Not found /block")

        runtime_filter.record_match(sample)
        runtime_filter.add_fingerprints({response_fingerprint(sample)})

        self.assertIsInstance(runtime_filter, DisabledRuntimeFilter)
        self.assertFalse(runtime_filter.is_filtered(sample))
        self.assertEqual(runtime_filter.recalibration_events, [])

    def test_preflight_runtime_filter_records_repeated_matches(self):
        runtime_filter = build_runtime_filter(True)
        responses = [
            runtime_response(
                f"block-{index}",
                f"Not found /block-{index}".encode(),
            )
            for index in range(RUNTIME_MATCH_STREAK_THRESHOLD)
        ]

        for sample in responses:
            runtime_filter.record_match(sample)

        self.assertIsInstance(runtime_filter, PreflightRuntimeFilter)
        self.assertTrue(runtime_filter.is_filtered(responses[0]))
        self.assertEqual(
            runtime_filter.recalibration_events,
            ["repeated_match_fingerprint"],
        )

    def test_response_fingerprint_ignores_reflected_path_and_dynamic_tokens(self):
        first = runtime_response(
            "foo/block-1",
            b"Not found /foo/block-1. Request id 550e8400-e29b-41d4-a716-446655440000.",
        )
        second = runtime_response(
            "foo/block-2",
            b"Not found /foo%2Fblock-2. Request id 550e8400-e29b-41d4-a716-446655440001.",
        )

        self.assertEqual(response_fingerprint(first), response_fingerprint(second))

    def test_response_fingerprint_preserves_bare_path_normalization(self):
        first = runtime_response(
            "missing-1",
            b"missing missing-1 soft 404 body with repeated template content",
        )
        second = runtime_response(
            "missing-2",
            b"missing missing-2 soft 404 body with repeated template content",
        )

        self.assertEqual(response_fingerprint(first), response_fingerprint(second))

    def test_response_fingerprint_uses_stable_digest_between_processes(self):
        script = """
from lib.connection.response import NativeResponse
from lib.core.runtime_fingerprint import response_fingerprint
response = NativeResponse(
    "https://example.com/block-1",
    200,
    [("content-type", "text/html")],
    b"Not found /block-1. Request id 550e8400-e29b-41d4-a716-446655440000.",
)
print(response_fingerprint(response)[-1])
"""
        digests = []
        for seed in ("1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                env=env,
                text=True,
            )
            digests.append(result.stdout.strip())

        self.assertEqual(digests[0], digests[1])
        self.assertEqual(len(digests[0]), 64)

    def test_repeated_match_recalibration_waits_for_threshold(self):
        responses = [
            runtime_response(
                f"block-{index}",
                f"Not found /block-{index}".encode(),
            )
            for index in range(RUNTIME_MATCH_STREAK_THRESHOLD - 1)
        ]

        self.assertEqual(repeated_match_recalibration(responses), (set(), None))

    def test_repeated_match_recalibration_returns_common_fingerprint(self):
        responses = [
            runtime_response(
                f"block-{index}",
                f"Not found /block-{index}".encode(),
            )
            for index in range(RUNTIME_MATCH_STREAK_THRESHOLD)
        ]

        fingerprints, reason = repeated_match_recalibration(responses)

        self.assertEqual(reason, "repeated_match_fingerprint")
        self.assertEqual(fingerprints, {response_fingerprint(responses[0])})
