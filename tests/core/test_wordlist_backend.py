from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

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

    def test_native_rejects_an_incompatible_extension(self):
        incompatible_native = type(
            "IncompatibleNativeModule",
            (),
            {"__version__": "0.2.0"},
        )()

        with (
            patch.dict("sys.modules", {"dirsearch_native": incompatible_native}),
            self.assertRaisesRegex(
                WordlistBackendUnavailableError,
                r"expected 0\.2\.1, found 0\.2\.0",
            ),
        ):
            NativeWordlistBackend()

    def test_percent_encoded_paths_do_not_force_python_expansion(self):
        backend = object.__new__(NativeWordlistBackend)
        with tempfile.TemporaryDirectory() as temp_dir:
            wordlist = Path(temp_dir) / "wordlist.txt"
            wordlist.write_text(
                "%2e%2e/etc/passwd\nvalue%20with%20spaces\n",
                encoding="utf-8",
            )

            self.assertFalse(
                backend._requires_python_template_expansion([str(wordlist)])
            )

    def test_named_templates_still_use_python_expansion(self):
        backend = object.__new__(NativeWordlistBackend)
        with tempfile.TemporaryDirectory() as temp_dir:
            wordlist = Path(temp_dir) / "wordlist.txt"
            wordlist.write_text("%SUBJECT%/admin\n", encoding="utf-8")

            self.assertTrue(
                backend._requires_python_template_expansion([str(wordlist)])
            )

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
