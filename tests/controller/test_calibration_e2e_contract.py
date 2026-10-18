"""Real CLI regressions for valid pages that used to disappear in calibration."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from urllib.parse import urlsplit

from tests.controller.test_backend_e2e_contract import (
    BackendContractHandler,
    BackendContractServer,
    NATIVE_AVAILABLE,
    REPOSITORY_ROOT,
)


SHARED_PREFIX = b"<html><head>" + b"shared-layout-word " * 300 + b"</head><body>"
DISTINCT_PAGES = {
    "/billing": SHARED_PREFIX + b"Billing information.</body></html>",
    "/support": SHARED_PREFIX + b"Support information.</body></html>",
    "/account/login": SHARED_PREFIX + b"Account credentials.</body></html>",
}
DUPLICATE_PATHS = {"/alias-first", "/alias-second", "/alias-third"}


class CalibrationContractHandler(BackendContractHandler):
    def do_GET(self):
        with self.server.seen_lock:
            self.server.seen_paths.append(self.path)

        if self.path == "/control":
            self.send_body(b"independent scan control", status=201)
        elif self.server.scenario == "prefix":
            if self.path in DISTINCT_PAGES:
                self.send_body(DISTINCT_PAGES[self.path], content_type="text/html")
            elif self.path in DUPLICATE_PATHS:
                self.send_body(b"an identical repeated page long enough for calibration")
            else:
                self.send_body(b"missing resource", status=404)
        elif self.path == "/account/login":
            self.send_body(b'{"authenticated":false,"login":"available"}', content_type="application/json")
        else:
            # Compact reflected-path JSON yields no shared whitespace tokens.
            body = json.dumps({"error": "missing", "path": self.path}, separators=(",", ":")).encode()
            with self.server.seen_lock:
                if self.server.first_negative is None:
                    self.server.first_negative = body
                if self.path == "/known-missing":
                    body = self.server.first_negative
            self.send_body(body, content_type="application/json")


class TestCalibrationEndToEndContract(TestCase):
    def run_case(self, backend, scenario, concurrency, forced):
        with BackendContractServer(CalibrationContractHandler) as server, TemporaryDirectory() as temporary:
            server.server.scenario = scenario
            server.server.first_negative = None
            directory = Path(temporary)
            config = directory / "config.ini"
            config.write_text("", encoding="utf-8")
            wordlist = directory / "words.txt"
            paths = (
                [*DISTINCT_PAGES, "/alias-first", "/alias-second", "/alias-third"]
                if scenario == "prefix" else ["/account/login"]
            )
            paths.extend(("/known-missing", "/control"))
            wordlist.write_text("\n".join(path.lstrip("/") for path in paths), encoding="utf-8")
            report = directory / "results.json"
            log = directory / "scan.log"
            command = [
                sys.executable, str(REPOSITORY_ROOT / "dirsearch.py"),
                "--config", str(config), "-u", server.url, "-w", str(wordlist),
                "--threads", str(concurrency), "--subdirs", "/", "--exclude-subdirs", "excluded/",
                "--timeout", "2", "--retries", "0", "--filter-threshold", "5",
                "--include-status", "200,201", "--no-color", "-O", "json", "-o", str(report),
                "--log", str(log), "--request-backend", "native" if backend == "native" else "python",
                "--async" if backend == "async" else "--no-async",
            ]
            if forced:
                command.append("--auto-calibration")
            environment = os.environ.copy()
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                environment.pop(name, None)
            environment["NO_PROXY"] = "127.0.0.1,localhost"
            environment["no_proxy"] = environment["NO_PROXY"]
            completed = subprocess.run(
                command, cwd=REPOSITORY_ROOT, env=environment, capture_output=True,
                text=True, timeout=30, check=False,
            )
            details = f"{backend}/{scenario}/{concurrency}/{forced}\n{completed.stdout}\n{completed.stderr}"
            self.assertEqual(completed.returncode, 0, details)
            self.assertTrue(report.is_file(), details)
            results = json.loads(report.read_text(encoding="utf-8"))["results"]
            matches = {urlsplit(item["url"]).path for item in results}
            self.assertTrue(set(paths).issubset(server.seen_paths), details)
            self.assertIn("/control", matches, details)
            self.assertNotIn("/known-missing", matches, details)
            self.assertEqual({item["status"] for item in results}, {200, 201}, details)
            if scenario == "prefix":
                self.assertTrue(set(DISTINCT_PAGES).issubset(matches), details)
                # Preserve intentional repeated-response filtering too. The
                # selected two aliases can depend on completion order.
                self.assertEqual(len(matches & DUPLICATE_PATHS), 2, details)
            else:
                self.assertEqual(matches, {"/account/login", "/control"}, details)
                self.assertIn("filtered by wildcard profile", log.read_text(encoding="utf-8"), details)

    def run_prefix_cases(self, backend):
        for concurrency in (1, 100):
            with self.subTest(concurrency=concurrency):
                self.run_case(backend, "prefix", concurrency, True)

    def run_json_cases(self, backend):
        for concurrency in (1, 100):
            for forced in (False, True):
                with self.subTest(concurrency=concurrency, forced=forced):
                    self.run_case(backend, "json", concurrency, forced)

    def test_threaded_keeps_distinct_pages_with_shared_prefix(self):
        self.run_prefix_cases("threaded")

    def test_async_keeps_distinct_pages_with_shared_prefix(self):
        self.run_prefix_cases("async")

    @skipUnless(NATIVE_AVAILABLE, "compatible native extension is not installed")
    def test_native_keeps_distinct_pages_with_shared_prefix(self):
        self.run_prefix_cases("native")

    def test_threaded_keeps_distinct_json_without_static_patterns(self):
        self.run_json_cases("threaded")

    def test_async_keeps_distinct_json_without_static_patterns(self):
        self.run_json_cases("async")

    @skipUnless(NATIVE_AVAILABLE, "compatible native extension is not installed")
    def test_native_keeps_distinct_json_without_static_patterns(self):
        self.run_json_cases("native")
