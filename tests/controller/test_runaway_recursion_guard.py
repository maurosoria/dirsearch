import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.settings import MAX_RECURSIVE_UNIFORM_RESPONSES


def make_response(status=200, length=1024, path="admin"):
    return SimpleNamespace(
        status=status,
        length=length,
        path=path,
        redirect="",
        history=[],
    )


class TestRunawayRecursionGuard(unittest.TestCase):
    def setUp(self):
        self.controller = object.__new__(Controller)
        self.controller._uniform_response_counts = {}
        self.controller._uniform_recursion_warned = set()

    def test_allows_recursion_below_threshold(self):
        response = make_response()

        for _ in range(MAX_RECURSIVE_UNIFORM_RESPONSES - 1):
            self.assertFalse(
                self.controller.is_runaway_recursion("/admin/", response)
            )

    def test_blocks_recursion_at_threshold_and_beyond(self):
        response = make_response()

        for _ in range(MAX_RECURSIVE_UNIFORM_RESPONSES - 1):
            self.controller.is_runaway_recursion("/admin/", response)

        for _ in range(5):
            self.assertTrue(
                self.controller.is_runaway_recursion("/admin/", response)
            )

    def test_warning_logged_once_per_branch(self):
        response = make_response()

        with patch("lib.controller.controller.interface") as mock_interface:
            for _ in range(MAX_RECURSIVE_UNIFORM_RESPONSES * 2):
                self.controller.is_runaway_recursion("/admin/", response)

        self.assertEqual(mock_interface.warning.call_count, 1)

    def test_counter_scoped_per_branch(self):
        response = make_response()

        for _ in range(MAX_RECURSIVE_UNIFORM_RESPONSES - 1):
            self.controller.is_runaway_recursion("/admin/", response)

        # Same fingerprint on a different branch starts from a fresh count
        self.assertFalse(self.controller.is_runaway_recursion("/blog/", response))

    def test_distinct_fingerprints_tracked_separately(self):
        first = make_response(status=200, length=1024)
        second = make_response(status=200, length=2048)

        for _ in range(MAX_RECURSIVE_UNIFORM_RESPONSES - 1):
            self.assertFalse(self.controller.is_runaway_recursion("/", first))
            self.assertFalse(self.controller.is_runaway_recursion("/", second))

    def test_match_callback_skips_recursion_when_guard_trips(self):
        controller = object.__new__(Controller)
        controller._uniform_response_counts = {}
        controller._uniform_recursion_warned = set()
        controller.directories = []
        controller.passed_urls = set()
        controller.url = "https://example.com/"
        controller.base_path = ""
        controller.fuzzer = SimpleNamespace(base_path="/")

        with patch.dict(
            options,
            {
                "recursion_status_codes": {200},
                "recursive": True,
                "deep_recursive": False,
                "force_recursive": False,
                "skip_on_status": set(),
                "full_url": False,
                "replay_proxy": None,
                "crawl": False,
                "exclude_subdirs": [],
                "recursion_depth": 0,
            },
        ), patch("lib.controller.controller.interface") as mock_interface:
            for i in range(MAX_RECURSIVE_UNIFORM_RESPONSES + 3):
                controller.match_callback(make_response(path=f"word{i}/"))

        added = len(controller.directories)
        self.assertEqual(added, MAX_RECURSIVE_UNIFORM_RESPONSES - 1)
        self.assertEqual(mock_interface.warning.call_count, 1)


if __name__ == "__main__":
    unittest.main()
