from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest import TestCase

import requests

from lib.core.data import options


class APITestHandler(BaseHTTPRequestHandler):
    routes = {
        "/admin.php": (200, b"admin"),
        "/login.php": (200, b"login"),
        "/private.txt": (200, b"private"),
    }

    def do_GET(self):
        self.server.seen.append((self.command, self.path, dict(self.headers), b""))
        if self.path == "/agent-only":
            status, body = (
                (200, b"agent")
                if self.headers.get("x-agent") == "yes"
                else (404, b"missing")
            )
            self.send_response(status)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        status, body = self.routes.get(self.path, (404, b"missing"))
        self.send_response(status)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_length = int(self.headers.get("content-length", 0))
        request_body = self.rfile.read(content_length)
        self.server.seen.append((self.command, self.path, dict(self.headers), request_body))

        status, body = (
            (200, b"raw")
            if (
                self.path == "/submit/probe?debug=true"
                and self.headers.get("x-raw") == "yes"
                and request_body == b"payload-\xff"
            )
            else (404, b"missing")
        )
        self.send_response(status)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class LocalHTTPServer:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), APITestHandler)
        self.server.seen = []
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}"
        self.host_header = f"{host}:{port}"
        self.seen = self.server.seen
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class TestImportableAPI(TestCase):
    def test_public_imports_are_available(self):
        from dirsearch import (
            DirsearchFuzzer,
            FuzzerConfig,
            FuzzerResult,
            PreflightResult,
            Wordlist,
            WordlistLimitError,
            WordlistState,
            WordlistTemplate,
        )

        self.assertIsNotNone(DirsearchFuzzer)
        self.assertIsNotNone(FuzzerConfig)
        self.assertIsNotNone(FuzzerResult)
        self.assertIsNotNone(PreflightResult)
        self.assertIsNotNone(Wordlist)
        self.assertIsNotNone(WordlistLimitError)
        self.assertIsNotNone(WordlistState)
        self.assertIsNotNone(WordlistTemplate)

    def test_builtin_template_and_wordlist_limit(self):
        from dirsearch import Wordlist, WordlistLimitError, WordlistTemplate

        template = WordlistTemplate.from_builtin(
            "admin",
            placeholders={
                "ADMIN_OP": ["admin"],
                "SUBJECT": ["users"],
            },
        )
        wordlist = Wordlist.from_template(
            template,
            extensions=("php",),
            max_entries=10,
        )

        self.assertIn("admin.php", wordlist.items)
        self.assertIn("admin/users", wordlist.items)

        broad_template = WordlistTemplate(
            ["%SUBJECT%.%EXT%"],
            placeholders={"SUBJECT": ["admin", "login"]},
        )
        with self.assertRaises(WordlistLimitError):
            Wordlist.from_template(
                broad_template,
                extensions=("php", "json"),
                max_entries=1,
            )

    def test_python_api_runs_template_wordlist_and_callbacks(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig, WordlistTemplate

        with LocalHTTPServer() as server:
            template = WordlistTemplate(
                ["%SUBJECT%.%EXT%", "missing.%EXT%"],
                placeholders={"SUBJECT": ["admin", "login"]},
            )
            seen = []
            not_found = []
            config = FuzzerConfig(
                url=server.url,
                wordlist=template,
                extensions=("php",),
            )

            results = DirsearchFuzzer(
                config,
                on_result=seen.append,
                on_not_found=not_found.append,
            ).run()

        self.assertEqual([result.path for result in results], ["admin.php", "login.php"])
        self.assertEqual([result.status for result in seen], [200, 200])
        self.assertEqual([result.path for result in not_found], ["missing.php"])

    def test_result_predicate_filters_custom_matches(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig

        with LocalHTTPServer() as server:
            not_found = []
            results = DirsearchFuzzer(
                FuzzerConfig(
                    url=server.url,
                    wordlist=["admin.php", "private.txt"],
                    result_predicate=lambda result: b"private" in result.body,
                ),
                on_not_found=not_found.append,
            ).run()

        self.assertEqual([result.path for result in results], ["private.txt"])
        self.assertEqual([result.path for result in not_found], ["admin.php"])

    def test_preflight_api_returns_result(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig

        with LocalHTTPServer() as server:
            fuzzer = DirsearchFuzzer(
                FuzzerConfig(
                    url=server.url,
                    wordlist=["admin.php"],
                    preflight=True,
                )
            )
            results = fuzzer.run()

        self.assertEqual([result.path for result in results], ["admin.php"])
        self.assertIsNotNone(fuzzer.preflight_result)
        self.assertTrue(fuzzer.preflight_result.enabled)

    def test_session_factory_customizes_requests(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig

        def session_factory():
            session = requests.Session()
            session.headers.update({"x-agent": "yes"})
            return session

        with LocalHTTPServer() as server:
            results = DirsearchFuzzer(
                FuzzerConfig(
                    url=server.url,
                    wordlist=["agent-only"],
                    include_status_codes={200},
                    session_factory=session_factory,
                )
            ).run()

        self.assertEqual([result.path for result in results], ["agent-only"])

    def test_from_raw_request_runs_with_body_and_query(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig

        with LocalHTTPServer() as server:
            raw_request = (
                b"POST /submit?debug=true HTTP/1.1\r\n"
                + f"Host: {server.host_header}\r\n".encode()
                + b"Content-Type: application/octet-stream\r\n"
                + b"X-Raw: yes\r\n"
                + b"\r\n"
                + b"payload-\xff"
            )
            results = DirsearchFuzzer(
                FuzzerConfig.from_raw_request(
                    raw_request=raw_request,
                    scheme="http",
                    wordlist=["probe"],
                    include_status_codes={200},
                )
            ).run()

        self.assertEqual([result.url for result in results], [f"{server.url}/submit/probe?debug=true"])
        self.assertEqual(server.seen[-1][0], "POST")
        self.assertEqual(server.seen[-1][1], "/submit/probe?debug=true")
        self.assertEqual(server.seen[-1][3], b"payload-\xff")

    def test_from_raw_request_file_uses_absolute_form_target(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig

        with LocalHTTPServer() as server, TemporaryDirectory() as directory:
            request_file = Path(directory, "request.txt")
            request_file.write_bytes(
                f"GET {server.url}/ HTTP/1.1\r\n".encode()
                + b"Host: proxy.local\r\n"
                + b"X-Agent: yes\r\n"
                + b"\r\n"
            )
            results = DirsearchFuzzer(
                FuzzerConfig.from_raw_request(
                    raw_file=str(request_file),
                    wordlist=["agent-only"],
                    include_status_codes={200},
                )
            ).run()

        self.assertEqual([result.path for result in results], ["agent-only"])

    def test_from_raw_request_requires_one_source(self):
        from dirsearch import FuzzerConfig

        with self.assertRaises(ValueError):
            FuzzerConfig.from_raw_request(wordlist=["admin"])

        with self.assertRaises(ValueError):
            FuzzerConfig.from_raw_request(
                raw_request=b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n",
                raw_file="request.txt",
                wordlist=["admin"],
            )

    def test_raise_on_error_invokes_callback_then_raises(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig

        class FailingSession(requests.Session):
            def request(self, *args, **kwargs):
                raise requests.ConnectionError("boom")

        errors = []
        fuzzer = DirsearchFuzzer(
            FuzzerConfig(
                url="https://example.com",
                wordlist=["admin"],
                session_factory=FailingSession,
                raise_on_error=True,
            ),
            on_error=errors.append,
        )

        with self.assertRaises(requests.ConnectionError):
            fuzzer.run()
        self.assertEqual(len(errors), 1)

    def test_two_configs_do_not_leak_state(self):
        from dirsearch import DirsearchFuzzer, FuzzerConfig, WordlistTemplate

        before = dict(options)
        mutable_wordlist = ["admin.php"]
        mutable_headers = {"x-api-test": "first"}
        frozen_config = FuzzerConfig(
            url="http://127.0.0.1",
            wordlist=mutable_wordlist,
            headers=mutable_headers,
        )
        mutable_wordlist.append("private.txt")
        mutable_headers["x-api-test"] = "second"

        with LocalHTTPServer() as server:
            first_template = WordlistTemplate(
                ["%SUBJECT%.%EXT%"],
                placeholders={"SUBJECT": ["admin"]},
            )
            second_template = WordlistTemplate(
                ["%SUBJECT%.%EXT%"],
                placeholders={"SUBJECT": ["private"]},
            )

            first = DirsearchFuzzer(
                FuzzerConfig(
                    url=server.url,
                    wordlist=first_template,
                    extensions=("php",),
                )
            ).run()
            second = DirsearchFuzzer(
                FuzzerConfig(
                    url=server.url,
                    wordlist=second_template,
                    extensions=("txt",),
                )
            ).run()

        self.assertEqual([result.path for result in first], ["admin.php"])
        self.assertEqual([result.path for result in second], ["private.txt"])
        self.assertEqual(list(frozen_config.wordlist), ["admin.php"])
        self.assertEqual(frozen_config.headers["x-api-test"], "first")
        self.assertEqual(options, before)
