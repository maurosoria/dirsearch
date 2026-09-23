from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from lib.connection.native import NativeHTTPBackend
from lib.connection.requester import AsyncRequester, Requester
from lib.connection.response import NativeResponse
from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import RequestException
from lib.parse.url import same_origin


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

    def test_excluded_subdirectory_matching_is_segment_aware(self):
        options["exclude_subdirs"] = ["admin/"]

        for path in ("admin/", "nested/admin/"):
            with self.subTest(path=path):
                self.controller.directories = []
                self.controller.passed_urls = set()
                self.controller.add_directory(path)
                self.assertEqual(self.controller.directories, [])

        self.controller.add_directory("administrator/")
        self.assertEqual(self.controller.directories, ["administrator/"])


class DirectoryRedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/directory":
            self.send_response(301)
            self.send_header("Location", self.server.redirect_location)
            body = b""
        else:
            self.send_response(200)
            body = b"ok"

        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        return None


class DirectoryRedirectServer:
    def __init__(self):
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            DirectoryRedirectHandler,
        )
        self.server.redirect_location = "/directory/"
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01),
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError("redirect fixture server did not stop")

    @property
    def url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}/"

    def redirect_to(self, location: str) -> None:
        self.server.redirect_location = location


class FollowedRedirectRecursionContract:
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "proxies": [],
                "headers": {},
                "data": None,
                "cert_file": None,
                "key_file": None,
                "network_interface": None,
                "random_agents": False,
                "auth": None,
                "auth_type": None,
                "max_retries": 0,
                "max_rate": 0,
                "thread_count": 1,
                "follow_redirects": True,
                "http_method": "GET",
                "timeout": 1,
                "proxy_auth": None,
                "skip_on_status": set(),
                "full_url": False,
                "recursion_status_codes": {200},
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

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    @staticmethod
    def queued_directories(response) -> list[str]:
        controller = object.__new__(Controller)
        controller._operation_lock = threading.Lock()
        controller.url = response.url.rsplit("/", 1)[0] + "/"
        controller.base_path = ""
        controller.directories = []
        controller.passed_urls = set()

        with patch("lib.controller.controller.interface"):
            controller.match_callback(response)

        return controller.directories

    def assert_same_origin_directory_redirect_recurs(self, response) -> None:
        self.assertEqual(response.status, 200)
        self.assertEqual(len(response.history), 1)
        self.assertEqual(response.final_url, f"{response.url}/")
        self.assertEqual(self.queued_directories(response), ["directory/"])

    def assert_cross_origin_directory_redirect_does_not_recur(self, response) -> None:
        self.assertEqual(response.status, 200)
        self.assertEqual(len(response.history), 1)
        self.assertFalse(same_origin(response.url, response.final_url))
        self.assertEqual(self.queued_directories(response), [])


class TestThreadedFollowedRedirectRecursion(
    FollowedRedirectRecursionContract,
    TestCase,
):
    def request(self, server: DirectoryRedirectServer):
        requester = Requester()
        requester.set_url(server.url)
        try:
            return requester.request("directory")
        finally:
            requester.close()

    def test_same_origin_directory_redirect_recurs(self):
        with DirectoryRedirectServer() as server:
            self.assert_same_origin_directory_redirect_recurs(self.request(server))

    def test_cross_origin_directory_redirect_does_not_recur(self):
        with DirectoryRedirectServer() as destination:
            with DirectoryRedirectServer() as origin:
                origin.redirect_to(f"{destination.url}directory/")
                self.assert_cross_origin_directory_redirect_does_not_recur(
                    self.request(origin)
                )


class TestAsyncFollowedRedirectRecursion(
    FollowedRedirectRecursionContract,
    IsolatedAsyncioTestCase,
):
    async def request(self, server: DirectoryRedirectServer):
        requester = AsyncRequester()
        requester.set_url(server.url)
        try:
            return await requester.request("directory")
        finally:
            await requester.close()

    async def test_same_origin_directory_redirect_recurs(self):
        with DirectoryRedirectServer() as server:
            self.assert_same_origin_directory_redirect_recurs(
                await self.request(server)
            )

    async def test_cross_origin_directory_redirect_does_not_recur(self):
        with DirectoryRedirectServer() as destination:
            with DirectoryRedirectServer() as origin:
                origin.redirect_to(f"{destination.url}directory/")
                self.assert_cross_origin_directory_redirect_does_not_recur(
                    await self.request(origin)
                )


class TestNativeFollowedRedirectRecursion(
    FollowedRedirectRecursionContract,
    TestCase,
):
    def request(self, server: DirectoryRedirectServer):
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        result = list(backend.scan(server.url, ["directory"]))[0]
        self.assertIsNone(result[2])
        return result[1]

    def test_same_origin_directory_redirect_recurs(self):
        with DirectoryRedirectServer() as server:
            self.assert_same_origin_directory_redirect_recurs(self.request(server))

    def test_cross_origin_directory_redirect_does_not_recur(self):
        with DirectoryRedirectServer() as destination:
            with DirectoryRedirectServer() as origin:
                origin.redirect_to(f"{destination.url}directory/")
                self.assert_cross_origin_directory_redirect_does_not_recur(
                    self.request(origin)
                )
