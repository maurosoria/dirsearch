from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.preflight import PreflightProfile, PreflightResult


class DummyFuzzer:
    def __init__(self) -> None:
        self.runtime_fingerprints = set()

    def add_runtime_fingerprints(self, fingerprints: set[tuple]) -> None:
        self.runtime_fingerprints.update(fingerprints)


class CapturingSyncPreflightCalibrator:
    seen_profiles: list[tuple[int, float, int, str]] = []

    def __init__(self, requester, dictionary, base_path: str = "") -> None:
        self.__class__.seen_profiles.append(
            (
                options["thread_count"],
                options["delay"],
                options["max_rate"],
                base_path,
            )
        )

    def run(self) -> PreflightResult:
        return PreflightResult(
            enabled=True,
            original_profile=PreflightProfile("original", 8, 0.0, 0),
            applied_profile=PreflightProfile("slow", 2, 0.15, 1),
            runtime_fingerprints={("runtime", "fingerprint")},
        )


class TestControllerPreflight(TestCase):
    def setUp(self) -> None:
        self.original_options = dict(options)
        options.update(
            {
                "preflight": True,
                "request_backend": "python",
                "async_mode": False,
                "thread_count": 8,
                "delay": 0.0,
                "max_rate": 0,
                "preflight_result": None,
            }
        )
        CapturingSyncPreflightCalibrator.seen_profiles = []

    def tearDown(self) -> None:
        options.clear()
        options.update(self.original_options)

    def test_preflight_starts_from_original_profile_after_previous_adjustment(self):
        controller = object.__new__(Controller)
        controller.requester = object()
        controller.dictionary = ["admin"]
        controller.fuzzer = DummyFuzzer()
        controller._preflight_original_profile = PreflightProfile("original", 8, 0.0, 0)

        options["thread_count"] = 2
        options["delay"] = 0.15
        options["max_rate"] = 1

        with patch(
            "lib.controller.controller.SyncPreflightCalibrator",
            CapturingSyncPreflightCalibrator,
        ), patch("lib.controller.controller.interface.warning"):
            controller.run_preflight("admin/")

        self.assertEqual(
            CapturingSyncPreflightCalibrator.seen_profiles,
            [(8, 0.0, 0, "admin/")],
        )
        self.assertEqual(options["thread_count"], 2)
        self.assertEqual(options["delay"], 0.15)
        self.assertEqual(options["max_rate"], 1)
        self.assertEqual(
            controller.fuzzer.runtime_fingerprints,
            {("runtime", "fingerprint")},
        )
