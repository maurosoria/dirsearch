from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import skipUnless, TestCase

from lib.core.data import options
from lib.core.exceptions import WordlistBackendUnavailableError
from lib.core.wordlist_backend import (
    NativeWordlistBackend,
    PythonWordlistBackend,
    get_wordlist_backend,
)


class TestWordlistBackend(TestCase):
    def setUp(self):
        self._original_options = dict(options)
        options["wordlist_backend"] = "auto"

    def tearDown(self):
        options.clear()
        options.update(self._original_options)

    def test_auto_selects_python_backend(self):
        self.assertIsInstance(get_wordlist_backend(), PythonWordlistBackend)

    def test_python_selects_python_backend(self):
        self.assertIsInstance(get_wordlist_backend("python"), PythonWordlistBackend)

    def test_native_reports_unavailable(self):
        try:
            backend = get_wordlist_backend("native")
        except WordlistBackendUnavailableError:
            return

        self.assertIsInstance(backend, NativeWordlistBackend)

    @skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_native_generation_releases_gil_and_propagates_signal(self):
        try:
            get_wordlist_backend("native")
        except WordlistBackendUnavailableError:
            self.skipTest("native extension is not installed")

        source = r'''
import os
import signal
import tempfile
import threading
import time
import dirsearch_native

class NativeWordlistInterrupted(Exception):
    pass

with tempfile.TemporaryDirectory() as directory:
    fifo = os.path.join(directory, "wordlist.fifo")
    os.mkfifo(fifo)

    def writer():
        with open(fifo, "wb", buffering=0) as handle:
            os.kill(os.getpid(), signal.SIGINT)
            handle.write(b"admin\n")

    previous = signal.getsignal(signal.SIGINT)
    thread = threading.Thread(target=writer)
    signal.signal(
        signal.SIGINT,
        lambda *_: (_ for _ in ()).throw(
            NativeWordlistInterrupted("stop native wordlist")
        ),
    )
    thread.start()
    started = time.monotonic()
    try:
        try:
            dirsearch_native.generate_wordlist([fifo], [])
        except NativeWordlistInterrupted as error:
            assert str(error) == "stop native wordlist"
        else:
            raise AssertionError("native generation ignored SIGINT")
    finally:
        signal.signal(signal.SIGINT, previous)
        thread.join(timeout=1)

    assert not thread.is_alive()
    assert time.monotonic() - started < 2
    print("native-wordlist-interrupted")
'''

        result = subprocess.run(
            [sys.executable, "-c", source],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "native-wordlist-interrupted")

    def test_native_matches_python_when_available(self):
        try:
            native = get_wordlist_backend("native")
        except WordlistBackendUnavailableError:
            return

        files = ["tests/static/wordlist.txt"]
        original = dict(options)
        options.update(
            {
                "extensions": ("php", "json"),
                "exclude_extensions": (),
                "force_extensions": True,
                "overwrite_extensions": False,
                "prefixes": (),
                "suffixes": (),
                "lowercase": False,
                "uppercase": False,
                "capitalization": False,
                "wordlist_max_size": 500000,
            }
        )
        try:
            python = get_wordlist_backend("python")
            self.assertEqual(
                native.generate(files),
                python.generate(files),
            )
        finally:
            options.clear()
            options.update(original)

    def test_native_preserves_unicode_and_replaces_invalid_bytes(self):
        try:
            native = get_wordlist_backend("native")
        except WordlistBackendUnavailableError:
            return

        expected = ["管理/登录", "مسار/دخول", "पथ/लॉगिन", "broken-�"]
        with tempfile.TemporaryDirectory() as temp_dir:
            wordlist = Path(temp_dir) / "wordlist.txt"
            wordlist.write_bytes(
                "管理/登录\nمسار/دخول\nपथ/लॉगिन\n".encode("utf-8")
                + b"broken-\xff\n"
            )
            options.update(
                {
                    "extensions": (),
                    "exclude_extensions": (),
                    "force_extensions": False,
                    "overwrite_extensions": False,
                    "prefixes": (),
                    "suffixes": (),
                    "lowercase": False,
                    "uppercase": False,
                    "capitalization": False,
                    "wordlist_max_size": 500000,
                }
            )

            self.assertEqual(native.generate([str(wordlist)]), expected)
            self.assertEqual(
                get_wordlist_backend("python").generate([str(wordlist)]),
                expected,
            )

    def test_wordlist_backends_are_independent_of_request_stack(self):
        backend_names = ["python"]
        try:
            get_wordlist_backend("native")
        except WordlistBackendUnavailableError:
            pass
        else:
            backend_names.append("native")

        request_stacks = (
            ("threaded", "python", False),
            ("async", "python", True),
            ("native", "native", False),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            wordlist = Path(temp_dir) / "wordlist.txt"
            wordlist.write_text("admin\n", encoding="utf-8")
            options.update(
                {
                    "extensions": (),
                    "exclude_extensions": (),
                    "force_extensions": False,
                    "overwrite_extensions": False,
                    "prefixes": (),
                    "suffixes": (),
                    "lowercase": False,
                    "uppercase": False,
                    "capitalization": False,
                    "wordlist_max_size": 500000,
                }
            )

            for backend_name in backend_names:
                for stack_name, request_backend, async_mode in request_stacks:
                    with self.subTest(
                        wordlist_backend=backend_name,
                        request_stack=stack_name,
                    ):
                        options.update(
                            {
                                "wordlist_backend": backend_name,
                                "request_backend": request_backend,
                                "async_mode": async_mode,
                            }
                        )
                        self.assertEqual(
                            get_wordlist_backend().generate([str(wordlist)]),
                            ["admin"],
                        )

    def test_native_matches_python_for_generation_options_when_available(self):
        try:
            native = get_wordlist_backend("native")
        except WordlistBackendUnavailableError:
            return

        test_cases = [
            {
                "lines": ["admin", "/root", "//double", "#comment", "", "file.%EXT%"],
                "options": {},
            },
            {
                "lines": ["admin", "dir/", "file.%EXT%"],
                "options": {"force_extensions": True},
            },
            {
                "lines": ["foo.asp", "bar.php", "baz.unknown", "q?a=.zip", "frag#x.txt"],
                "options": {"overwrite_extensions": True},
            },
            {
                "lines": ["foo.php", "bar.txt", "baz"],
                "options": {"exclude_extensions": ("php",)},
            },
            {
                "lines": ["admin", "dir/", "q?a=1", "frag#x"],
                "options": {"prefixes": ("pre-",), "suffixes": ("-suf",)},
            },
            {
                "lines": ["Admin", "admin"],
                "options": {"lowercase": True},
            },
            {
                "lines": ["ADMIN/path"],
                "options": {"capitalization": True},
            },
            {
                "lines": ["%SUBJECT%/admin"],
                "options": {},
            },
        ]
        default_options = {
            "extensions": ("php", "json"),
            "exclude_extensions": (),
            "force_extensions": False,
            "overwrite_extensions": False,
            "prefixes": (),
            "suffixes": (),
            "lowercase": False,
            "uppercase": False,
            "capitalization": False,
            "wordlist_max_size": 500000,
        }
        original = dict(options)
        try:
            for test_case in test_cases:
                with tempfile.TemporaryDirectory() as temp_dir:
                    wordlist = Path(temp_dir) / "wordlist.txt"
                    wordlist.write_text("\n".join(test_case["lines"]), encoding="utf-8")

                    options.update(default_options)
                    options.update(test_case["options"])

                    python = get_wordlist_backend("python")
                    self.assertEqual(
                        native.generate([str(wordlist)]),
                        python.generate([str(wordlist)]),
                    )
        finally:
            options.clear()
            options.update(original)
