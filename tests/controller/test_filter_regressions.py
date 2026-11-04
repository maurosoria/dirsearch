"""Finding and stop-policy regressions across the complete CLI engines."""

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


class FilterRegressionHandler(BackendContractHandler):
    def do_GET(self):
        with self.server.seen_lock:
            self.server.seen_paths.append(self.path)
        scenario = self.server.scenario
        if scenario == "stop-calibration" or (
            scenario == "stop-candidate" and self.path == "/valid"
        ):
            self.send_body(b"Too many requests; stop scanning this target", status=429)
        elif self.path == "/valid":
            body = b"admin\x1csecret" if scenario == "whitespace" else b"admin\n"
            if scenario in ("headers", "header-text"):
                self.send_response(200)
                self.send_header("X-Role", "first")
                self.send_header("x-role", "second")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_body(body)
        else:
            self.send_body(b"Missing page response", status=404)


class TestFilterRegressions(TestCase):
    def run_case(self, backend, scenario, flags=()):
        with BackendContractServer(FilterRegressionHandler) as server, TemporaryDirectory() as temporary:
            server.server.scenario = scenario
            directory = Path(temporary)
            config = directory / "config.ini"
            config.write_text("", encoding="utf-8")
            words = directory / "words.txt"
            words.write_text("valid\nlater\n", encoding="utf-8")
            report = directory / "report.json"
            command = [
                sys.executable, str(REPOSITORY_ROOT / "dirsearch.py"),
                "--config", str(config), "-u", server.url, "-w", str(words),
                "--threads", "1", "--timeout", "2", "--retries", "0", "--no-color",
                "--request-backend", "native" if backend == "native" else "python",
                "--async" if backend == "async" else "--no-async",
                "-O", "json", "-o", str(report), *flags,
            ]
            environment = os.environ.copy()
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                environment.pop(name, None)
            environment.update(NO_PROXY="*", no_proxy="*")
            completed = subprocess.run(
                command, cwd=REPOSITORY_ROOT, env=environment,
                capture_output=True, text=True, timeout=25, check=False,
            )
            output = completed.stdout + completed.stderr
            details = f"{backend}/{scenario}/{flags}\n{output}"
            self.assertEqual(completed.returncode, 0, details)
            matches = {
                urlsplit(item["url"]).path
                for item in json.loads(report.read_text())["results"]
            } if report.is_file() else set()
            if scenario.startswith("stop-"):
                self.assertIn("Skipped the target due to 429 status code", output, details)
                self.assertEqual(matches, set(), details)
                if scenario == "stop-calibration":
                    self.assertNotIn("/valid", server.seen_paths, details)
            else:
                self.assertIn("/valid", server.seen_paths, details)
                self.assertEqual(matches, {"/valid"}, details)

    def run_result_cases(self, backend):
        cases = (
            ("empty-exclusions", ()),
            ("trailing-comma", ("--exclude-subdirs", "cache/,")),
            ("regex", ("--match-regex", "admin$")),
            ("regex-flags", ("--match-regex", "(?a)admin$")),
            ("regex-or", ("--matcher-mode", "or", "--match-status", "201", "--match-regex", "admin$")),
            ("regex-and", ("--filter-mode", "and", "--filter-status", "200", "--filter-regex", "never")),
            ("whitespace", ("--match-regex", r"admin\ssecret")),
            ("headers", ("--match-header-regex", "x-role: first, second")),
            ("header-text", ("--match-header", "x-role: first, second")),
        )
        for scenario, flags in cases:
            with self.subTest(scenario=scenario):
                if scenario not in ("empty-exclusions", "trailing-comma"):
                    flags = ("--exclude-subdirs", "cache/", *flags)
                self.run_case(backend, scenario, flags)

    def run_stop_cases(self, backend):
        for scenario in ("stop-calibration", "stop-candidate"):
            with self.subTest(scenario=scenario):
                self.run_case(backend, scenario, (
                    "--exclude-subdirs", "cache/", "--skip-on-status", "429",
                    "--exclude-status", "429",
                ))

    def test_threaded_keeps_findings(self):
        self.run_result_cases("threaded")

    def test_async_keeps_findings(self):
        self.run_result_cases("async")

    @skipUnless(NATIVE_AVAILABLE, "matching native extension unavailable")
    def test_native_keeps_findings(self):
        self.run_result_cases("native")

    def test_threaded_stop_precedes_calibration_and_filters(self):
        self.run_stop_cases("threaded")

    def test_async_stop_precedes_calibration_and_filters(self):
        self.run_stop_cases("async")

    @skipUnless(NATIVE_AVAILABLE, "matching native extension unavailable")
    def test_native_stop_precedes_calibration_and_filters(self):
        self.run_stop_cases("native")
