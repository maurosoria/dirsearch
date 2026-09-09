import json
import subprocess
import sys
from unittest import TestCase


class TestReportCommandRedaction(TestCase):
    def test_all_command_report_formats_use_redacted_metadata(self):
        secret = "REPORT_ARTIFACT_SECRET"
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
    "json": json.dumps(JSONReport().new()),
    "xml": XMLReport().new().attrib["args"],
    "html": HTMLReport().new(),
}))
"""
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                f"--auth={secret}",
                "--threads",
                "7",
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
        for report_format, payload in payloads.items():
            with self.subTest(report_format=report_format):
                self.assertNotIn(secret, payload)
                self.assertIn("redacted", payload)
                self.assertIn("--threads 7", payload)
