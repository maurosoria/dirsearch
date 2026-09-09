import json
import subprocess
import sys
from html import unescape
from unittest import TestCase

from lib.utils.command import REDACTED_VALUE


class TestReportCommandRedaction(TestCase):
    def test_all_command_report_formats_use_redacted_metadata(self):
        secret_values = (
            "test-password",
            "test-access-token",
            "test-session-id",
            "test-csrf-token",
            "test-body-password",
            "test-proxy-password",
            "test-proxy-auth",
            "test-mysql-password",
            "test-postgres-password",
            "test-target-password",
        )
        expected_command = " ".join(
            [
                "-c",
                f"--auth={REDACTED_VALUE}",
                "-H",
                REDACTED_VALUE,
                f"--cookie={REDACTED_VALUE}",
                "--data",
                REDACTED_VALUE,
                f"--proxy={REDACTED_VALUE}",
                "--proxy-auth",
                REDACTED_VALUE,
                f"--mysql-url={REDACTED_VALUE}",
                "--postgres-url",
                REDACTED_VALUE,
                f"--url={REDACTED_VALUE}",
                "--auth-type",
                "basic",
                "--threads",
                "7",
                "--crawl",
            ]
        )
        script = """
import json
from lib.report.html_report import HTMLReport
from lib.report.json_report import JSONReport
from lib.report.markdown_report import MarkdownReport
from lib.report.plain_text_report import PlainTextReport
from lib.report.xml_report import XMLReport

print(json.dumps({
    "plain": PlainTextReport().new(),
    "markdown": MarkdownReport().new(),
    "json": JSONReport().new()["info"]["args"],
    "xml": XMLReport().new().attrib["args"],
    "html": HTMLReport().new(),
}))
"""
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                "--auth=test-user:test-password",
                "-H",
                "Authorization: Bearer test-access-token",
                "--cookie=session_id=test-session-id; csrf=test-csrf-token",
                "--data",
                "username=test-user&password=test-body-password",
                "--proxy=http://proxy-user:test-proxy-password"
                "@proxy.example.test:8080",
                "--proxy-auth",
                "test-proxy-user:test-proxy-auth",
                "--mysql-url=mysql://db-user:test-mysql-password"
                "@db.example.test/app",
                "--postgres-url",
                "postgresql://db-user:test-postgres-password"
                "@db.example.test/app",
                "--url=https://scan-user:test-target-password"
                "@target.example.test/private",
                "--auth-type",
                "basic",
                "--threads",
                "7",
                "--crawl",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payloads = json.loads(completed.stdout)

        self.assertEqual(
            set(payloads),
            {"plain", "markdown", "json", "xml", "html"},
        )
        payloads["html"] = unescape(payloads["html"])
        for report_format, payload in payloads.items():
            with self.subTest(report_format=report_format):
                for secret_value in secret_values:
                    self.assertNotIn(secret_value, payload)
                self.assertIn(expected_command, payload)

        self.assertEqual(payloads["json"], expected_command)
        self.assertEqual(payloads["xml"], expected_command)
