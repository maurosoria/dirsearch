import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from lib.connection.response import NativeResponse
from lib.core.report_config import ReportConfig
from lib.core.run_metadata import RunMetadata
from lib.report.html_report import HTMLReport
from lib.report.json_report import JSONReport
from lib.report.manager import ReportManager
from lib.report.markdown_report import MarkdownReport
from lib.report.plain_text_report import PlainTextReport
from lib.report.xml_report import XMLReport


class TestReportRunMetadata(TestCase):
    def test_managers_capture_each_invocation_not_module_import_time(self):
        with TemporaryDirectory() as directory:
            managers = []
            try:
                for name, started in (
                    ("first", "2026-10-05 23:59:59"),
                    ("second", "2026-10-06 00:00:01"),
                ):
                    with (
                        patch("sys.argv", ["dirsearch", "--auth", name + "-secret", "-u", "https://" + name + ".test/"]),
                        patch("time.strftime", return_value=started),
                    ):
                        manager = ReportManager(ReportConfig(
                            formats=("json",),
                            output_file=str(Path(directory, name + "-{date}.json")),
                        ))
                    managers.append(manager)

                # Render in reverse order, after argv/clock have changed again.
                for manager in reversed(managers):
                    manager.prepare("https://example.test/")
                for name, date, started in (
                    ("first", "2026-10-05", "2026-10-05 23:59:59"),
                    ("second", "2026-10-06", "2026-10-06 00:00:01"),
                ):
                    report = json.loads(Path(directory, name + "-" + date + ".json").read_text())
                    self.assertEqual(report["info"], {
                        "args": "dirsearch --auth <redacted> -u https://" + name + ".test/",
                        "time": started,
                    })
            finally:
                for manager in managers:
                    manager.finish()

    def test_all_metadata_formats_use_the_explicit_value_at_render_time(self):
        with patch("time.strftime", return_value="2026-10-05 23:59:59"):
            metadata = RunMetadata.capture(["dirsearch", "--auth", "report-secret"])
        directory = self.enterContext(TemporaryDirectory())
        with patch.object(RunMetadata, "capture", side_effect=AssertionError("metadata recaptured")):
            manager = ReportManager(ReportConfig(
                formats=("json", "xml", "html", "plain", "md"),
                output_file=str(Path(directory, "{datetime}-{format}.{extension}")),
            ), metadata=metadata)
            self.addCleanup(manager.finish)
            for reporter, _ in manager.reports:
                self.assertIs(reporter.metadata, metadata)
            manager.prepare("https://first.test/")
            manager.prepare("https://second.test/")
            manager.save(NativeResponse("https://first.test/item", 200, [], b"found"))
            manager.flush()
            reports = list(Path(directory).iterdir())
            self.assertEqual(len(reports), 5)
            for report in reports:
                with self.subTest(format=report.suffix):
                    self.assertTrue(report.name.startswith("2026-10-05_23-59-59-"))
                    content = report.read_text(encoding="utf-8")
                    self.assertIn("2026-10-05 23:59:59", content)
                    self.assertIn("dirsearch --auth", content)
                    self.assertIn("redacted", content)
                    self.assertNotIn("report-secret", content)
                    self.assertIn("https://first.test/item", content)

    def test_standalone_report_constructors_capture_once_not_per_render(self):
        for report_class in (JSONReport, XMLReport, HTMLReport, PlainTextReport, MarkdownReport):
            with self.subTest(format=report_class.__format__):
                with patch("sys.argv", ["dirsearch", "--auth", "standalone-secret"]):
                    reporter = report_class()
                with patch.object(RunMetadata, "capture", side_effect=AssertionError("metadata recaptured")):
                    first = reporter.new()
                    second = reporter.new()
                self.assertEqual(reporter.metadata.command, "dirsearch --auth <redacted>")
                if report_class is XMLReport:
                    self.assertEqual(first.attrib, second.attrib)
                else:
                    self.assertEqual(first, second)

    def test_reopening_json_and_xml_preserves_existing_header_metadata(self):
        original = RunMetadata("original-command", "2026-10-05 12:00:00")
        current = RunMetadata("resumed-command", "2026-10-06 12:00:00")
        with TemporaryDirectory() as directory:
            config = ReportConfig(
                formats=("json", "xml"), output_file=str(Path(directory, "report.{extension}")),
            )
            for metadata in (original, current):
                manager = ReportManager(config, metadata=metadata)
                try:
                    manager.prepare("https://example.test/")
                    manager.flush()
                finally:
                    manager.finish()
            self.assertEqual(json.loads(Path(directory, "report.json").read_text())["info"], {
                "args": original.command, "time": original.start_time,
            })
            root = XMLReport(metadata=current).parse(Path(directory, "report.xml"))
            self.assertEqual(root.attrib, {"args": original.command, "time": original.start_time})
