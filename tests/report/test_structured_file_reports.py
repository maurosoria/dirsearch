# -*- coding: utf-8 -*-

import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lib.core.exceptions import FileExistsException
from lib.report.html_report import HTMLReport
from lib.report.json_report import JSONReport
from lib.report.xml_report import XMLReport
from lib.utils.file import FileUtils


STRUCTURED_REPORTS = (
    (JSONReport, "json"),
    (XMLReport, "xml"),
    (HTMLReport, "html"),
)


def make_result(url):
    return SimpleNamespace(
        datetime="2026-09-25 10:00:00",
        url=url,
        status=200,
        length=42,
        type="text/plain",
        redirect="",
        elapsed=0.25,
    )


def result_urls(report, destination):
    data = report.parse(destination)
    if isinstance(report, JSONReport):
        return [entry["url"] for entry in data["results"]]
    if isinstance(report, XMLReport):
        return [entry.attrib["url"] for entry in data.findall("result")]
    return [entry["url"] for entry in data]


class TestStructuredFileReports(TestCase):
    def test_large_batches_parse_once_and_write_one_final_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"large-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)

                    with patch.object(
                        report,
                        "parse",
                        wraps=report.parse,
                    ) as parse, patch.object(
                        report,
                        "write",
                        wraps=report.write,
                    ) as write:
                        for index in range(250):
                            report.save(
                                destination,
                                make_result(f"https://example.test/{index}"),
                            )
                        report.finish()

                    self.assertEqual(parse.call_count, 1)
                    self.assertEqual(write.call_count, 1)
                    self.assertEqual(len(result_urls(report, destination)), 250)

    def test_existing_reports_are_parsed_once_then_extended(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"resume-{report_class.__name__}.{extension}",
                    )
                    original = report_class()
                    original.initiate(destination)
                    original.save(
                        destination,
                        make_result("https://example.test/existing"),
                    )
                    original.finish()

                    resumed = report_class()
                    with patch.object(
                        resumed,
                        "parse",
                        wraps=resumed.parse,
                    ) as parse, patch.object(
                        resumed,
                        "write",
                        wraps=resumed.write,
                    ) as write:
                        resumed.initiate(destination)
                        for index in range(20):
                            resumed.save(
                                destination,
                                make_result(f"https://example.test/new-{index}"),
                            )
                        resumed.finish()

                    self.assertEqual(parse.call_count, 2)
                    self.assertEqual(write.call_count, 1)
                    urls = result_urls(resumed, destination)
                    self.assertEqual(urls[0], "https://example.test/existing")
                    self.assertEqual(len(urls), 21)

    def test_failed_snapshot_is_recovered_from_the_durable_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"failure-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    original = Path(destination).read_bytes()
                    pending_url = "https://example.test/pending"
                    report.save(destination, make_result(pending_url))

                    with patch.object(
                        report,
                        "write",
                        side_effect=OSError("injected snapshot failure"),
                    ):
                        with self.assertRaisesRegex(
                            OSError,
                            "injected snapshot failure",
                        ):
                            report.finish()

                    self.assertEqual(Path(destination).read_bytes(), original)
                    self.assertTrue(Path(report.journal_path(destination)).is_file())

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.finish()

                    self.assertEqual(result_urls(recovered, destination), [pending_url])
                    self.assertFalse(Path(recovered.journal_path(destination)).exists())

    def test_failed_journal_append_does_not_accept_the_result_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"append-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)

                    with patch.object(
                        FileUtils,
                        "append_private_text",
                        side_effect=OSError("injected journal failure"),
                    ):
                        with self.assertRaisesRegex(
                            OSError,
                            "injected journal failure",
                        ):
                            report.save(
                                destination,
                                make_result("https://example.test/rejected"),
                            )

                    report.finish()

                    self.assertEqual(result_urls(report, destination), [])

    def test_invalid_journal_is_rejected_without_changing_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"invalid-{report_class.__name__}.{extension}",
                    )
                    original = report_class()
                    original.initiate(destination)
                    original.finish()
                    original_bytes = Path(destination).read_bytes()
                    Path(original.journal_path(destination)).write_text(
                        '{"kind":"not-a-dirsearch-journal"}\n',
                        encoding="utf-8",
                    )

                    with self.assertRaises(FileExistsException):
                        report_class().initiate(destination)

                    self.assertEqual(Path(destination).read_bytes(), original_bytes)

    def test_journal_does_not_overwrite_a_conflicting_valid_report(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"conflict-{report_class.__name__}.{extension}",
                    )
                    external = os.path.join(
                        directory,
                        f"external-{report_class.__name__}.{extension}",
                    )
                    pending = report_class()
                    pending.initiate(destination)
                    pending.save(
                        destination,
                        make_result("https://example.test/pending"),
                    )

                    replacement = report_class()
                    replacement.initiate(external)
                    replacement.save(
                        external,
                        make_result("https://example.test/external"),
                    )
                    replacement.finish()
                    shutil.copyfile(external, destination)
                    external_bytes = Path(destination).read_bytes()

                    with self.assertRaises(FileExistsException):
                        report_class().initiate(destination)

                    self.assertEqual(Path(destination).read_bytes(), external_bytes)

    def test_committed_journal_is_not_replayed_after_cleanup_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"cleanup-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    url = "https://example.test/once"
                    report.save(destination, make_result(url))

                    with patch.object(
                        FileUtils,
                        "remove",
                        side_effect=OSError("injected cleanup failure"),
                    ):
                        report.finish()

                    self.assertEqual(result_urls(report, destination), [url])
                    self.assertTrue(Path(report.journal_path(destination)).exists())

                    report.finish()
                    second_url = "https://example.test/after-cleanup"
                    report.save(destination, make_result(second_url))
                    report.finish()
                    self.assertEqual(
                        result_urls(report, destination),
                        [url, second_url],
                    )

                    report.save(
                        destination,
                        make_result("https://example.test/recover-once"),
                    )
                    with patch.object(
                        FileUtils,
                        "remove",
                        side_effect=OSError("injected cleanup failure"),
                    ):
                        report.finish()

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.finish()

                    self.assertEqual(
                        result_urls(recovered, destination),
                        [url, second_url, "https://example.test/recover-once"],
                    )
                    self.assertFalse(Path(recovered.journal_path(destination)).exists())

    def test_repeated_initiate_and_finish_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"repeat-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    report.initiate(destination)
                    url = "https://example.test/once"
                    report.save(destination, make_result(url))
                    report.finish()
                    report.finish()
                    second_url = "https://example.test/twice"
                    report.save(destination, make_result(second_url))
                    report.finish()

                    self.assertEqual(
                        result_urls(report, destination),
                        [url, second_url],
                    )

    def test_one_reporter_flushes_every_prepared_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    first = os.path.join(directory, f"first.{extension}")
                    second = os.path.join(directory, f"second.{extension}")
                    report = report_class()
                    report.initiate(first)
                    report.initiate(second)
                    report.save(first, make_result("https://first.example/"))
                    report.save(second, make_result("https://second.example/"))
                    report.finish()

                    self.assertEqual(
                        result_urls(report, first),
                        ["https://first.example/"],
                    )
                    self.assertEqual(
                        result_urls(report, second),
                        ["https://second.example/"],
                    )

    def test_flush_attempts_every_destination_before_reraising(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    first = os.path.join(directory, f"failed.{extension}")
                    second = os.path.join(directory, f"written.{extension}")
                    report = report_class()
                    report.initiate(first)
                    report.initiate(second)
                    report.save(first, make_result("https://first.example/"))
                    report.save(second, make_result("https://second.example/"))
                    real_write = report.write

                    def fail_first(destination, data):
                        if destination == first:
                            raise OSError("injected first destination failure")
                        return real_write(destination, data)

                    with patch.object(report, "write", side_effect=fail_first):
                        with self.assertRaisesRegex(
                            OSError,
                            "injected first destination failure",
                        ):
                            report.finish()

                    self.assertEqual(
                        result_urls(report, second),
                        ["https://second.example/"],
                    )
                    self.assertTrue(Path(report.journal_path(first)).exists())
                    report.finish()
                    self.assertEqual(
                        result_urls(report, first),
                        ["https://first.example/"],
                    )
