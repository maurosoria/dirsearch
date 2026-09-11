import threading
from unittest import TestCase
from unittest.mock import patch

from lib.connection.response import NativeResponse
from lib.controller.controller import Controller
from lib.core.data import options


def redirect_response(location: str) -> NativeResponse:
    return NativeResponse(
        "https://example.test/admin",
        301,
        [("Location", location)],
        b"",
    )


class TestRedirectRecursionOrigin(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "skip_on_status": set(),
                "full_url": False,
                "recursion_status_codes": {301},
                "recursive": True,
                "deep_recursive": False,
                "force_recursive": False,
                "replay_proxy": None,
                "crawl": False,
                "find_backup": False,
                "exclude_subdirs": [],
                "recursion_depth": 0,
            }
        )

        self.controller = object.__new__(Controller)
        self.controller._operation_lock = threading.Lock()
        self.controller.url = "https://example.test/"
        self.controller.base_path = ""

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def queued_directories(self, location: str) -> list[str]:
        self.controller.directories = []
        self.controller.passed_urls = set()

        with patch("lib.controller.controller.interface"):
            self.controller.match_callback(redirect_response(location))

        return self.controller.directories

    def test_cross_origin_redirects_do_not_recur_on_the_target(self):
        locations = (
            "https://other.test/admin/",
            "//other.test/admin/",
            "http://example.test/admin/",
            "https://example.test:444/admin/",
            "https://example.test:0/admin/",
            "https://[invalid/admin/",
        )

        for location in locations:
            with self.subTest(location=location):
                self.assertEqual(self.queued_directories(location), [])

    def test_same_origin_redirects_still_recur(self):
        locations = (
            "/admin/",
            "admin/",
            "https://example.test/admin/",
            "https://EXAMPLE.TEST:443/admin/",
            "//EXAMPLE.TEST:443/admin/",
        )

        for location in locations:
            with self.subTest(location=location):
                self.assertEqual(self.queued_directories(location), ["admin/"])
