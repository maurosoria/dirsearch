import io
import os
import tempfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from lib.core.options import parse_options
from lib.core.settings import COMMON_EXTENSIONS


class TestOptions(TestCase):
    def test_quoted_extension_wildcard_uses_common_extensions(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "*",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["extensions"], COMMON_EXTENSIONS)

    def test_async_socks4_proxy_is_rejected_before_requester_setup(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--async",
            "--proxy",
            "socks4://127.0.0.1:1080",
        ]
        output = io.StringIO()

        with (
            patch("sys.argv", args),
            redirect_stderr(output),
            self.assertRaises(SystemExit) as ctx,
        ):
            parse_options()

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn(
            "--async supports SOCKS5 proxies only",
            output.getvalue(),
        )

    def test_data_file_preserves_request_body_bytes(self):
        bodies = {
            "ascii": b"alpha=1&beta=2\r\nline=two\n",
            "utf-8": "value=\u00e9&city=\u6771\u4eac\r\n".encode("utf-8"),
            "windows-1252": "value=\u00e9&currency=\u20ac\r\n".encode("cp1252"),
        }

        for encoding, body in bodies.items():
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as directory:
                data_path = os.path.join(directory, "request-body.bin")
                with open(data_path, "wb") as data_file:
                    data_file.write(body)
                args = [
                    "dirsearch.py",
                    "--wordlist-status",
                    "-e",
                    "php",
                    "--data-file",
                    data_path,
                ]

                with patch("sys.argv", args):
                    parsed = parse_options()

            self.assertEqual(parsed["data"], body)

    def test_inline_data_remains_text(self):
        body = "value=\u00e9"
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--data",
            body,
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["data"], body)

    def test_aggressive_wordlist_category_is_opt_in(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--wordlist-categories",
            "aggressive",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        project_root = Path(__file__).parents[2]
        aggressive = project_root / "db" / "categories" / "aggressive.txt"
        traversal = r"\..\..\..\..\..\..\..\..\..\etc\passwd"
        self.assertEqual(parsed["wordlists"], [str(aggressive)])
        self.assertIn(
            traversal,
            aggressive.read_text(encoding="utf-8").splitlines(),
        )
        for default_wordlist in (
            project_root / "db" / "dicc.txt",
            project_root / "db" / "categories" / "common.txt",
        ):
            with self.subTest(default_wordlist=default_wordlist):
                self.assertNotIn(
                    traversal,
                    default_wordlist.read_text(encoding="utf-8").splitlines(),
                )

    def test_find_backup_cli_option_is_enabled(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--find-backup",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertTrue(parsed["find_backup"])

    def test_find_backup_is_loaded_from_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "config.ini")
            with open(config_path, "w", encoding="utf-8") as config:
                config.write("[advanced]\nfind-backup = True\n")
            args = [
                "dirsearch.py",
                "--wordlist-status",
                "-e",
                "php",
                "--config",
                config_path,
            ]

            with patch("sys.argv", args):
                parsed = parse_options()

        self.assertTrue(parsed["find_backup"])

    def test_save_response_cli_path_is_absolute(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--save-response",
            "relative-responses",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(
            parsed["save_response"],
            os.path.abspath("relative-responses"),
        )

    def test_save_response_jsonl_cli_path_is_absolute(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--save-response-jsonl",
            "relative-responses.jsonl",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(
            parsed["save_response_jsonl"],
            os.path.abspath("relative-responses.jsonl"),
        )

    def test_save_response_is_loaded_from_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "config.ini")
            with open(config_path, "w", encoding="utf-8") as config:
                config.write(
                    "[output]\n"
                    "save-response = configured-responses\n"
                    "save-response-jsonl = configured-responses.jsonl\n"
                )
            args = [
                "dirsearch.py",
                "--wordlist-status",
                "-e",
                "php",
                "--config",
                config_path,
            ]

            with patch("sys.argv", args):
                parsed = parse_options()

        self.assertEqual(
            parsed["save_response"],
            os.path.abspath("configured-responses"),
        )
        self.assertEqual(
            parsed["save_response_jsonl"],
            os.path.abspath("configured-responses.jsonl"),
        )

    def test_response_size_options_accept_raw_bytes_and_units(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--exclude-sizes",
            "512,1KB,2MB",
            "--min-response-size",
            "1KB",
            "--max-response-size",
            "2MB",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["exclude_sizes"], {512, 1024, 2 * 1024 * 1024})
        self.assertEqual(parsed["minimum_response_size"], 1024)
        self.assertEqual(parsed["maximum_response_size"], 2 * 1024 * 1024)

    def test_response_size_options_accept_bytes_suffix(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--exclude-sizes",
            "1024B",
            "--min-response-size",
            "512B",
            "--max-response-size",
            "2048B",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["exclude_sizes"], {1024})
        self.assertEqual(parsed["minimum_response_size"], 512)
        self.assertEqual(parsed["maximum_response_size"], 2048)

    def test_header_filter_options_are_parsed(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--match-header",
            "etag: w/",
            "--filter-header",
            "x-cache: fallback",
            "--match-header-regex",
            "etag: .+",
            "--filter-header-regex",
            "x-cache: fallback-[0-9]+",
        ]

        with patch("sys.argv", args):
            parsed = parse_options()

        self.assertEqual(parsed["match_headers"], ["etag: w/"])
        self.assertEqual(parsed["filter_headers"], ["x-cache: fallback"])
        self.assertEqual(parsed["match_header_regex"], "etag: .+")
        self.assertEqual(parsed["filter_header_regex"], "x-cache: fallback-[0-9]+")

    def test_invalid_header_regex_exits(self):
        args = [
            "dirsearch.py",
            "--wordlist-status",
            "-e",
            "php",
            "--filter-header-regex",
            "(",
        ]

        with patch("sys.argv", args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_options()
