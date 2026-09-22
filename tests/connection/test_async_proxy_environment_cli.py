"""End-to-end coverage for async scans with inherited proxy settings."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from urllib.parse import urlsplit

from tests.connection.proxy_server import ProxyTestStack
from tests.core.test_importable_api import LocalHTTPServer


class TestAsyncProxyEnvironmentCLI(TestCase):
    @staticmethod
    def _clean_proxy_environment():
        environment = os.environ.copy()
        for key in tuple(environment):
            if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
                environment.pop(key)
        return environment

    @staticmethod
    def _run_scan(url, environment, ip_address=None):
        project_root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            wordlist = Path(directory, "words.txt")
            wordlist.write_text("admin.php\n", encoding="utf-8")
            command = [
                sys.executable,
                str(project_root / "dirsearch.py"),
                "-u",
                url,
                "-w",
                str(wordlist),
                "-e",
                "php",
                "--threads",
                "1",
                "--timeout",
                "2",
                "--retries",
                "0",
                "--no-color",
            ]
            if ip_address is not None:
                command.extend(("--ip", ip_address))

            return subprocess.run(
                command,
                cwd=project_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

    def test_inherited_http_proxy_reports_a_match(self):
        environment = self._clean_proxy_environment()
        with LocalHTTPServer() as target, ProxyTestStack() as stack:
            environment.update(
                {
                    "HTTP_PROXY": stack.http_proxy.url,
                    "HTTPS_PROXY": stack.http_proxy.url,
                    "NO_PROXY": "",
                }
            )
            result = self._run_scan(target.url, environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("/admin.php", result.stdout)
            self.assertIn("/admin.php", [path for _, path, _, _ in target.seen])
            self.assertTrue(
                any(
                    method == "GET" and path.endswith("/admin.php")
                    for method, path in stack.http_proxy.events
                )
            )

    def test_no_proxy_target_keeps_ip_override_and_reports_a_match(self):
        environment = self._clean_proxy_environment()

        # The target is bound only to 127.0.0.1. Without the scoped transport,
        # NO_PROXY sends this URL to 127.0.0.2 and misses /admin.php.
        environment.update(
            {
                "HTTP_PROXY": "http://127.0.0.1:1",
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "NO_PROXY": "127.0.0.2",
            }
        )

        with LocalHTTPServer() as target:
            port = urlsplit(target.url).port
            result = self._run_scan(
                f"http://127.0.0.2:{port}/", environment, ip_address="127.0.0.1"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("/admin.php", result.stdout)
            self.assertIn("/admin.php", [path for _, path, _, _ in target.seen])
