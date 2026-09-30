import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from urllib.parse import urlsplit

from lib.core.native_runtime import NATIVE_EXTENSION_VERSION


try:
    import dirsearch_native
except ImportError:
    dirsearch_native = None


NATIVE_AVAILABLE = (
    dirsearch_native is not None
    and getattr(dirsearch_native, "__version__", None) == NATIVE_EXTENSION_VERSION
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MATCH_PATHS = {
    "/crawl-child",
    "/crawl-only",
    "/found/",
    "/redirect",
}


class BackendContractHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        with self.server.seen_lock:
            self.server.seen_paths.append(self.path)

        if self.path == "/":
            self.send_body(
                b'<html><a href="/crawl-only">crawl root</a></html>',
                content_type="text/html",
            )
        elif self.path == "/crawl-only":
            self.send_body(
                b'<html><a href="/crawl-child">crawl child</a></html>',
                content_type="text/html",
                status=201,
            )
        elif self.path == "/crawl-child":
            self.send_body(b"unique crawl child", status=201)
        elif self.path == "/found/":
            self.send_body(b"unique recursive directory", status=201)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/redirect/")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        elif self.path == "/redirect/":
            self.send_body(b"unique redirect destination", status=201)
        else:
            # Keep the soft 404 inside --include-status so only wildcard
            # classification, rather than a status filter, can discard it.
            self.send_body(b"shared soft 404 response")

    def send_body(self, body, *, content_type="text/plain", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class BackendContractServer:
    def __init__(self):
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            BackendContractHandler,
        )
        self.server.seen_paths = []
        self.server.seen_lock = threading.Lock()
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="backend-contract-server",
        )

    @property
    def url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}/"

    @property
    def seen_paths(self):
        with self.server.seen_lock:
            return set(self.server.seen_paths)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError("backend contract server did not stop")


class TestBackendEndToEndContract(TestCase):
    def run_contract(self, backend):
        with BackendContractServer() as server, TemporaryDirectory() as directory:
            directory = Path(directory)
            wordlist = directory / "wordlist.txt"
            config = directory / "config.ini"
            report = directory / "report.json"
            wordlist.write_text("found/\nredirect\nwildcard\n", encoding="utf-8")
            config.write_text("", encoding="utf-8")

            command = [
                sys.executable,
                str(REPOSITORY_ROOT / "dirsearch.py"),
                "--config",
                str(config),
                "--url",
                server.url,
                "--wordlists",
                str(wordlist),
                "--threads",
                "2",
                "--subdirs",
                "/",
                "--exclude-subdirs",
                "excluded/",
                "--timeout",
                "2",
                "--retries",
                "0",
                "--crawl",
                "--recursive",
                "--max-recursion-depth",
                "1",
                "--recursion-status",
                "201",
                "--follow-redirects",
                "--include-status",
                "200,201",
                "--output-formats",
                "json",
                "--output-file",
                str(report),
                "--no-color",
            ]
            if backend == "async":
                command.extend(("--request-backend", "python", "--async"))
            elif backend == "native":
                command.extend(("--request-backend", "native", "--no-async"))
            else:
                command.extend(("--request-backend", "python", "--no-async"))

            environment = os.environ.copy()
            for name in (
                "ALL_PROXY",
                "HTTPS_PROXY",
                "HTTP_PROXY",
                "all_proxy",
                "https_proxy",
                "http_proxy",
            ):
                environment.pop(name, None)
            environment["NO_PROXY"] = "127.0.0.1,localhost"
            environment["no_proxy"] = environment["NO_PROXY"]

            completed = subprocess.run(
                command,
                cwd=REPOSITORY_ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"{backend} backend failed\nstdout:\n{completed.stdout}"
                f"\nstderr:\n{completed.stderr}",
            )

            results = json.loads(report.read_text(encoding="utf-8"))["results"]
            matched_paths = {
                urlsplit(result["url"]).path
                for result in results
            }
            matched_statuses = {result["status"] for result in results}
            seen_paths = server.seen_paths

        self.assertEqual(
            matched_paths,
            EXPECTED_MATCH_PATHS,
            f"{backend} backend matched {matched_paths}; requested {seen_paths}"
            f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        self.assertEqual(matched_statuses, {201})
        self.assertIn("/wildcard", seen_paths)
        self.assertIn("/found/wildcard", seen_paths)
        self.assertIn("/redirect/wildcard", seen_paths)
        self.assertIn("/redirect/", seen_paths)
        return matched_paths

    def test_threaded_and_async_engines_follow_the_same_contract(self):
        threaded = self.run_contract("threaded")
        asynchronous = self.run_contract("async")

        self.assertEqual(threaded, asynchronous)

    @skipUnless(NATIVE_AVAILABLE, "compatible native extension is not installed")
    def test_native_engine_follows_the_same_contract(self):
        self.assertEqual(self.run_contract("native"), EXPECTED_MATCH_PATHS)
