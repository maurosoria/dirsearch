# -*- coding: utf-8 -*-

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib.mcp import server


class FakeMCP:
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.tools = {}
        self.run_calls = []

    def tool(self, func):
        self.tools[func.__name__] = func
        return func

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


class TestMCPServer(unittest.TestCase):
    def test_build_cli_args_for_structured_scan(self):
        args = server.build_cli_args(
            url="https://example.com",
            wordlists=["one.txt", "two.txt"],
            extensions="php,html",
            threads=3,
            recursive=True,
            include_status="200,301-302",
            headers={"X-Test": "1"},
            max_time=5,
        )

        self.assertIn("https://example.com", args)
        self.assertIn("one.txt,two.txt", args)
        self.assertIn("php,html", args)
        self.assertIn("--recursive", args)
        self.assertIn("X-Test: 1", args)
        self.assertIn("--max-time", args)

    def test_sanitize_cli_args_removes_mcp_managed_flags(self):
        args = server.sanitize_cli_args(
            [
                "-u",
                "https://example.com",
                "-O",
                "plain",
                "--output-file=report.txt",
                "--stdin",
                "--session",
                "old-session",
                "-Ojson",
                "-oreport.txt",
                "--recursive",
            ]
        )

        self.assertEqual(args, ["-u", "https://example.com", "--recursive"])

    def test_build_command_forces_json_output(self):
        output_file = os.path.join("tmp", "report.json")
        command = server.build_command(
            ["-u", "https://example.com", "-O", "plain", "-o", "report.txt"],
            output_file,
            default_max_time=10,
        )

        self.assertIn("dirsearch.py", command[1])
        self.assertIn("--no-color", command)
        self.assertIn("--quiet-mode", command)
        self.assertEqual(command[-4:], ["-O", "json", "-o", output_file])
        self.assertNotIn("plain", command)
        self.assertNotIn("report.txt", command)
        self.assertIn("10", command)

    def test_create_mcp_registers_two_tools(self):
        with patch.object(server, "FastMCP", FakeMCP):
            mcp = server.create_mcp()

        self.assertIn("dirsearch_scan", mcp.tools)
        self.assertIn("dirsearch_scan_cli", mcp.tools)

    def test_dirsearch_scan_cli_tool_uses_raw_args(self):
        with patch.object(server, "FastMCP", FakeMCP):
            mcp = server.create_mcp()

        with patch.object(server, "run_dirsearch", return_value={"ok": True}) as run_dirsearch:
            result = mcp.tools["dirsearch_scan_cli"](["-u", "https://example.com"], max_time=9)

        self.assertTrue(result["ok"])
        run_dirsearch.assert_called_once_with(["-u", "https://example.com"], max_time=9)

    def test_http_mode_starts_without_auth(self):
        fake_mcp = FakeMCP("dirsearch")
        with patch.object(server, "create_mcp", return_value=fake_mcp) as create_mcp:
            server.main(
                [
                    "--mcp",
                    "--mcp-transport",
                    "http",
                    "--mcp-host",
                    "127.0.0.1",
                    "--mcp-port",
                    "8123",
                    "--mcp-path",
                    "/api/mcp/",
                ]
            )

        create_mcp.assert_called_once_with(None)
        self.assertEqual(
            fake_mcp.run_calls[0],
            {
                "transport": "http",
                "host": "127.0.0.1",
                "port": 8123,
                "path": "/api/mcp/",
                "show_banner": False,
            },
        )

    def test_http_mode_with_custom_token(self):
        fake_mcp = FakeMCP("dirsearch")
        with patch.object(server, "create_mcp", return_value=fake_mcp) as create_mcp:
            with patch.object(sys, "stderr"):
                server.main(
                    [
                        "--mcp",
                        "--mcp-transport",
                        "http",
                        "--mcp-token",
                        "my-secret-token",
                    ]
                )

        create_mcp.assert_called_once_with("my-secret-token")

    def test_http_mode_auto_generates_token_when_flag_without_value(self):
        fake_mcp = FakeMCP("dirsearch")
        with patch.object(server, "create_mcp", return_value=fake_mcp) as create_mcp:
            with patch.object(server.secrets, "token_urlsafe", return_value="auto-generated-token") as gen:
                with patch.object(sys, "stderr"):
                    server.main(
                        [
                            "--mcp",
                            "--mcp-transport",
                            "http",
                            "--mcp-token",
                        ]
                    )

        gen.assert_called_once_with(32)
        create_mcp.assert_called_once_with("auto-generated-token")

    def test_run_dirsearch_reads_report_and_deletes_temp_file(self):
        fd, temp_report = tempfile.mkstemp(prefix="dirsearch-test-", suffix=".json")
        os.close(fd)
        os.unlink(temp_report)

        completed = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "done", "stderr": ""},
        )()

        def fake_mkstemp(prefix, suffix):
            fd = os.open(temp_report, os.O_CREAT | os.O_RDWR)
            return fd, temp_report

        def fake_run(*args, **kwargs):
            with open(temp_report, "w", encoding="utf-8") as fh:
                json.dump({"results": [{"url": "https://example.com/admin"}]}, fh)
            return completed

        with patch.object(server.tempfile, "mkstemp", side_effect=fake_mkstemp):
            with patch.object(server.subprocess, "run", side_effect=fake_run):
                result = server.run_dirsearch(["-u", "https://example.com"], max_time=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["report"]["results"][0]["url"], "https://example.com/admin")
        self.assertFalse(os.path.exists(temp_report))


if __name__ == "__main__":
    unittest.main()
