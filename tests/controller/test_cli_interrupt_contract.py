"""Real CLI signal delivery against a bounded loopback fixture (POSIX only)."""

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from tests.controller.test_backend_e2e_contract import (
    BackendContractHandler,
    BackendContractServer,
    NATIVE_AVAILABLE,
    REPOSITORY_ROOT,
)


class InterruptHandler(BackendContractHandler):
    def do_GET(self):
        if self.path != "/pause":
            return super().do_GET()
        self.server.request_started.set()
        if not self.server.release_response.wait(timeout=10):
            return
        try:
            self.send_body(b"pause fixture", status=201)
        except (BrokenPipeError, ConnectionResetError):
            # Cancellation may close the client before the response is sent.
            pass


class InterruptServer(BackendContractServer):
    def __init__(self):
        super().__init__()
        self.server.RequestHandlerClass = InterruptHandler
        self.server.request_started = threading.Event()
        self.server.release_response = threading.Event()

    def __exit__(self, *args):
        self.server.release_response.set()
        super().__exit__(*args)


@skipUnless(os.name == "posix", "subprocess SIGINT/SIGTERM delivery requires POSIX")
class TestCLIInterruptContract(TestCase):
    def run_interrupt_contract(self, backend):
        for number in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(backend=backend, signal=number):
                with InterruptServer() as server, TemporaryDirectory() as directory:
                    wordlist = Path(directory, "wordlist.txt")
                    config = Path(directory, "config.ini")
                    wordlist.write_text("pause\n", encoding="utf-8")
                    config.write_text("", encoding="utf-8")
                    command = [
                        sys.executable, str(REPOSITORY_ROOT / "dirsearch.py"),
                        "--config", str(config), "--url", server.url,
                        "--wordlists", str(wordlist), "--threads", "1",
                        "--subdirs", "/", "--exclude-subdirs", "excluded/",
                        "--timeout", "5", "--retries", "0", "--no-color",
                        "--request-backend", "native" if backend == "native" else "python",
                        "--async" if backend == "async" else "--no-async",
                    ]
                    environment = os.environ.copy()
                    for key in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
                        environment.pop(key, None)
                    environment["NO_PROXY"] = environment["no_proxy"] = "127.0.0.1,localhost"

                    process = subprocess.Popen(
                        command, cwd=REPOSITORY_ROOT, env=environment,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True,
                    )
                    try:
                        if not server.server.request_started.wait(timeout=10):
                            if process.poll() is None:
                                process.kill()
                            output, errors = process.communicate(timeout=5)
                            self.fail("CLI never reached the scan request\n" + output + errors)
                        process.send_signal(number)
                        server.server.release_response.set()
                        output, errors = process.communicate("q\nq\n", timeout=15)
                    finally:
                        server.server.release_response.set()
                        if process.poll() is None:
                            process.kill()
                        process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, output + errors)
                    self.assertIn("CTRL+C detected", output)
                    self.assertIn("[q]uit / [c]ontinue", output)
                    self.assertIn("Canceled by the user", output)
                    self.assertNotIn("Traceback", errors)
                    self.assertNotIn("was never awaited", errors)

    def test_threaded_cli_interrupts(self):
        self.run_interrupt_contract("threaded")

    def test_async_cli_interrupts(self):
        self.run_interrupt_contract("async")

    @skipUnless(NATIVE_AVAILABLE, "compatible native extension is not installed")
    def test_native_cli_interrupts(self):
        self.run_interrupt_contract("native")
