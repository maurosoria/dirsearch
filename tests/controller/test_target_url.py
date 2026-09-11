from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import os
import socket
import threading
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from lib.connection.native import NativeHTTPBackend
from lib.connection.requester import AsyncRequester, Requester
from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import InvalidURLException, RequestException


PROXY_ENVIRONMENT = {
    name: ""
    for name in (
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "http_proxy",
        "https_proxy",
    )
}
IPV6_LOOPBACK_FORMS = ("::1", "0:0:0:0:0:0:0:1")


class IPv6HTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True


class IPv6RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.targets.append(self.path)
        body = b"ipv6 ok"
        self.send_response(200)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class LocalIPv6HTTPServer:
    def __enter__(self):
        self.server = IPv6HTTPServer(("::1", 0), IPv6RequestHandler)
        self.server.targets = []
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01),
            daemon=True,
        )
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def url_for(self, hostname):
        port = self.server.server_address[1]
        return f"http://[{hostname}]:{port}/"

    @property
    def targets(self):
        return self.server.targets


class TestControllerTargetURL(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "request_backend": "python",
                "scheme": None,
                "ip": None,
                "proxies": [],
                "tor": False,
            }
        )
        self.controller = object.__new__(Controller)
        self.controller.requester = Mock()

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_ipv6_target_authority_keeps_literal_brackets(self):
        cases = (
            ("http://[::]/", "http://[::]/"),
            ("http://[::1]/", "http://[::1]/"),
            (
                "http://[0:0:0:0:0:0:0:1]/",
                "http://[0:0:0:0:0:0:0:1]/",
            ),
            (
                "http://[2001:0db8:0000:0000:0000:ff00:0042:8329]/",
                "http://[2001:0db8:0000:0000:0000:ff00:0042:8329]/",
            ),
            (
                "http://[2001:db8::ff00:42:8329]/",
                "http://[2001:db8::ff00:42:8329]/",
            ),
            ("http://[2001:db8::]/", "http://[2001:db8::]/"),
            ("http://[2001:DB8::ABCD]/", "http://[2001:db8::abcd]/"),
            (
                "http://[::ffff:192.0.2.128]/",
                "http://[::ffff:192.0.2.128]/",
            ),
            (
                "http://[64:ff9b::192.0.2.33]/",
                "http://[64:ff9b::192.0.2.33]/",
            ),
            (
                "https://[2001:db8::1]:443/private",
                "https://[2001:db8::1]/",
            ),
            (
                "http://[2001:db8::2]:8080/api",
                "http://[2001:db8::2]:8080/",
            ),
            (
                "http://[fe80::1%25eth0]:8000/",
                "http://[fe80::1%25eth0]:8000/",
            ),
        )

        for target, expected_url in cases:
            with self.subTest(target=target):
                self.controller.requester.reset_mock()

                self.controller.set_target(target)

                self.assertEqual(self.controller.url, expected_url)
                self.controller.requester.set_url.assert_called_once_with(
                    expected_url
                )

    def test_scheme_option_keeps_ipv6_literal_brackets(self):
        options["scheme"] = "https"

        self.controller.set_target("[2001:db8::1]:8443/private")

        self.assertEqual(self.controller.url, "https://[2001:db8::1]:8443/")
        self.controller.requester.set_url.assert_called_once_with(
            "https://[2001:db8::1]:8443/"
        )

    def test_invalid_ports_raise_invalid_url_exception(self):
        targets = (
            "http://example.test:not-a-port/",
            "http://example.test:-1/",
            "http://example.test:65536/",
            "http://example.test:０/",
            "http://[::1]:not-a-port/",
        )

        for request_backend in ("python", "native"):
            options["request_backend"] = request_backend
            for target in targets:
                with self.subTest(
                    request_backend=request_backend,
                    target=target,
                ):
                    with self.assertRaisesRegex(
                        InvalidURLException,
                        "Invalid port in target URL",
                    ):
                        self.controller.set_target(target)

    def test_invalid_port_does_not_discard_later_targets(self):
        stack_cases = (
            ("threaded", False, "python"),
            ("async", True, "python"),
            ("native", False, "native"),
        )

        for stack, async_mode, request_backend in stack_cases:
            with self.subTest(stack=stack):
                controller = object.__new__(Controller)
                controller.start_time = 0
                controller.passed_urls = set()
                controller.directories = []
                controller.jobs_processed = 0
                controller.errors = 0
                controller.consecutive_errors = 0
                controller.old_session = False
                controller.dictionary = Mock()
                controller.output_history = []
                controller.response_stores = ()
                controller.reporter = Mock()
                controller.crawl_target = Mock()
                controller.start = Mock()
                requester = Mock()

                run_options = {
                    "urls": [
                        "http://bad.example:not-a-port/",
                        "https://good.example/",
                    ],
                    "request_backend": request_backend,
                    "async_mode": async_mode,
                    "subdirs": [""],
                    "session_file": None,
                }

                with (
                    patch.dict(options, run_options),
                    patch(
                        "lib.connection.requester.Requester",
                        return_value=requester,
                    ),
                    patch(
                        "lib.connection.requester.AsyncRequester",
                        return_value=requester,
                    ),
                    patch("lib.core.fuzzer.Fuzzer", return_value=Mock()),
                    patch("lib.core.fuzzer.AsyncFuzzer", return_value=Mock()),
                    patch("lib.core.fuzzer.NativeFuzzer", return_value=Mock()),
                    patch("lib.controller.controller.signal.signal"),
                    patch("lib.controller.controller.interface") as interface,
                ):
                    try:
                        controller.run()
                    finally:
                        loop = getattr(controller, "loop", None)
                        if isinstance(loop, asyncio.AbstractEventLoop):
                            loop.close()

                controller.start.assert_called_once_with()
                controller.reporter.prepare.assert_called_once_with(
                    "https://good.example/"
                )
                interface.error.assert_called_once()
                self.assertIn(
                    "Invalid port in target URL",
                    interface.error.call_args.args[0],
                )

    def test_threaded_requester_reaches_ipv6_literal(self):
        with patch.dict(os.environ, PROXY_ENVIRONMENT):
            with LocalIPv6HTTPServer() as server:
                requester = Requester()
                self.controller.requester = requester
                try:
                    for hostname in IPV6_LOOPBACK_FORMS:
                        with self.subTest(hostname=hostname):
                            self.controller.set_target(server.url_for(hostname))
                            response = requester.request("ipv6-check")
                            self.assertEqual(response.status, 200)
                finally:
                    requester.close()

        self.assertEqual(server.targets, ["/ipv6-check", "/ipv6-check"])

    def test_native_requester_reaches_ipv6_literal(self):
        options["request_backend"] = "native"
        try:
            backend = NativeHTTPBackend()
        except RequestException as error:
            self.skipTest(str(error))

        with patch.dict(os.environ, PROXY_ENVIRONMENT):
            with LocalIPv6HTTPServer() as server:
                requester = Requester()
                self.controller.requester = requester
                try:
                    for hostname in IPV6_LOOPBACK_FORMS:
                        with self.subTest(hostname=hostname):
                            self.controller.set_target(server.url_for(hostname))
                            results = list(backend.scan(requester._url, ["ipv6-check"]))
                            self.assertIsNone(results[0][2])
                            self.assertEqual(results[0][1].status, 200)
                finally:
                    requester.close()

        self.assertEqual(server.targets, ["/ipv6-check", "/ipv6-check"])


class TestAsyncControllerTargetURL(IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "request_backend": "python",
                "scheme": None,
                "ip": None,
                "proxies": [],
                "tor": False,
            }
        )
        self.controller = object.__new__(Controller)

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    async def test_async_requester_reaches_ipv6_literal(self):
        with patch.dict(os.environ, PROXY_ENVIRONMENT):
            with LocalIPv6HTTPServer() as server:
                requester = AsyncRequester()
                self.controller.requester = requester
                try:
                    for hostname in IPV6_LOOPBACK_FORMS:
                        with self.subTest(hostname=hostname):
                            self.controller.set_target(server.url_for(hostname))
                            response = await requester.request("ipv6-check")
                            self.assertEqual(response.status, 200)
                finally:
                    await requester.close()

        self.assertEqual(server.targets, ["/ipv6-check", "/ipv6-check"])
