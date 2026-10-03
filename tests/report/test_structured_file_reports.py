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


def truncate_final_journal_record(report, destination):
    journal = Path(report.journal_path(destination))
    lines = journal.read_text(encoding="utf-8").splitlines()
    journal.write_text(
        "\n".join((*lines[:-1], lines[-1][:-4])),
        encoding="utf-8",
    )
    return journal


class TestStructuredFileReports(TestCase):
    def test_truncated_final_record_recovers_only_complete_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"truncated-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    kept_url = "https://example.test/complete"
                    report.save(destination, make_result(kept_url))
                    report.save(
                        destination,
                        make_result("https://example.test/interrupted"),
                    )

                    journal = truncate_final_journal_record(report, destination)

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.save(
                        destination,
                        make_result("https://example.test/after-recovery"),
                    )
                    recovered.finish()

                    self.assertEqual(
                        result_urls(recovered, destination),
                        [kept_url, "https://example.test/after-recovery"],
                    )
                    self.assertFalse(journal.exists())

    def test_truncated_record_preserves_original_journal_until_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"preserve-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    kept_url = "https://example.test/complete"
                    report.save(destination, make_result(kept_url))
                    report.save(
                        destination,
                        make_result("https://example.test/interrupted"),
                    )

                    journal = truncate_final_journal_record(report, destination)
                    original_journal = journal.read_bytes()
                    original_report = Path(destination).read_bytes()

                    interrupted = report_class()
                    with patch.object(
                        interrupted,
                        "write",
                        side_effect=OSError("injected recovery snapshot failure"),
                    ):
                        with self.assertRaises(FileExistsException) as raised:
                            interrupted.initiate(destination)

                    self.assertIsInstance(raised.exception.__cause__, OSError)

                    recovery = Path(interrupted.recovery_journal_path(destination))
                    self.assertEqual(Path(destination).read_bytes(), original_report)
                    self.assertEqual(recovery.read_bytes(), original_journal)

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.finish()

                    self.assertEqual(result_urls(recovered, destination), [kept_url])
                    self.assertFalse(journal.exists())
                    self.assertFalse(recovery.exists())

    def test_repaired_journal_creation_failure_restores_original(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"repair-failure-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    kept_url = "https://example.test/complete"
                    report.save(destination, make_result(kept_url))
                    report.save(
                        destination,
                        make_result("https://example.test/interrupted"),
                    )
                    journal = truncate_final_journal_record(report, destination)
                    recovery = Path(report.recovery_journal_path(destination))
                    original_journal = journal.read_bytes()
                    original_snapshot = Path(destination).read_bytes()

                    interrupted = report_class()
                    with patch.object(
                        FileUtils,
                        "atomic_write_private_text",
                        side_effect=OSError("injected repaired journal failure"),
                    ):
                        with self.assertRaises(FileExistsException) as raised:
                            interrupted.initiate(destination)

                    self.assertIsInstance(raised.exception.__cause__, OSError)
                    self.assertEqual(journal.read_bytes(), original_journal)
                    self.assertFalse(recovery.exists())
                    self.assertEqual(
                        Path(destination).read_bytes(),
                        original_snapshot,
                    )

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.finish()

                    self.assertEqual(result_urls(recovered, destination), [kept_url])
                    self.assertFalse(journal.exists())
                    self.assertFalse(recovery.exists())

    def test_restart_restores_journal_moved_before_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"repair-crash-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    kept_url = "https://example.test/complete"
                    report.save(destination, make_result(kept_url))
                    report.save(
                        destination,
                        make_result("https://example.test/interrupted"),
                    )
                    journal = truncate_final_journal_record(report, destination)
                    recovery = Path(report.recovery_journal_path(destination))
                    original_journal = journal.read_bytes()
                    os.replace(journal, recovery)

                    self.assertFalse(journal.exists())
                    self.assertEqual(recovery.read_bytes(), original_journal)

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.finish()

                    self.assertEqual(result_urls(recovered, destination), [kept_url])
                    self.assertFalse(journal.exists())
                    self.assertFalse(recovery.exists())

    def test_truncated_utf8_character_in_final_record_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"truncated-utf8-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    kept_url = "https://example.test/complete"
                    report.save(destination, make_result(kept_url))
                    report.save(
                        destination,
                        make_result("https://example.test/interrupted-💥"),
                    )

                    journal = Path(report.journal_path(destination))
                    lines = journal.read_bytes().splitlines(keepends=True)
                    emoji = "💥".encode("utf-8")
                    emoji_offset = lines[-1].index(emoji)
                    journal.write_bytes(
                        b"".join(lines[:-1])
                        + lines[-1][: emoji_offset + 2]
                    )

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.finish()

                    self.assertEqual(result_urls(recovered, destination), [kept_url])
                    self.assertFalse(journal.exists())

    def test_truncated_tail_after_committed_snapshot_replays_only_new_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"truncated-commit-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    committed_url = "https://example.test/committed"
                    pending_url = "https://example.test/pending"
                    report.save(destination, make_result(committed_url))
                    with patch.object(
                        FileUtils,
                        "remove",
                        side_effect=OSError("injected cleanup failure"),
                    ):
                        report.finish()

                    report.save(destination, make_result(pending_url))
                    report.save(
                        destination,
                        make_result("https://example.test/interrupted"),
                    )
                    journal = truncate_final_journal_record(report, destination)

                    recovered = report_class()
                    recovered.initiate(destination)
                    recovered.finish()

                    self.assertEqual(
                        result_urls(recovered, destination),
                        [committed_url, pending_url],
                    )
                    self.assertFalse(journal.exists())

    def test_malformed_middle_record_is_not_treated_as_truncated(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                with self.subTest(report=report_class.__name__):
                    destination = os.path.join(
                        directory,
                        f"middle-{report_class.__name__}.{extension}",
                    )
                    report = report_class()
                    report.initiate(destination)
                    report.save(
                        destination,
                        make_result("https://example.test/first"),
                    )
                    report.save(
                        destination,
                        make_result("https://example.test/second"),
                    )
                    original_report = Path(destination).read_bytes()

                    journal = Path(report.journal_path(destination))
                    lines = journal.read_text(encoding="utf-8").splitlines(
                        keepends=True
                    )
                    lines[1] = '{"entry":\n'
                    journal.write_text("".join(lines), encoding="utf-8")

                    with self.assertRaises(FileExistsException):
                        report_class().initiate(destination)

                    self.assertEqual(Path(destination).read_bytes(), original_report)

    def test_complete_invalid_final_record_is_rejected(self):
        invalid_records = (
            '{"entry":,}\n',
            '{"entry":,}',
            '{"kind":"result"}',
            '{"kind":"resu',
        )
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                for record_index, invalid_record in enumerate(invalid_records):
                    with self.subTest(
                        report=report_class.__name__,
                        invalid_record=invalid_record,
                    ):
                        destination = os.path.join(
                            directory,
                            f"complete-invalid-{report_class.__name__}."
                            f"{record_index}.{extension}",
                        )
                        report = report_class()
                        report.initiate(destination)
                        report.save(
                            destination,
                            make_result("https://example.test/complete"),
                        )
                        original_report = Path(destination).read_bytes()

                        journal = Path(report.journal_path(destination))
                        lines = journal.read_text(encoding="utf-8").splitlines(
                            keepends=True
                        )
                        journal.write_text(
                            "".join((*lines[:-1], invalid_record)),
                            encoding="utf-8",
                        )

                        with self.assertRaises(FileExistsException):
                            report_class().initiate(destination)

                        self.assertEqual(
                            Path(destination).read_bytes(),
                            original_report,
                        )

    def test_empty_or_blank_journal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for report_class, extension in STRUCTURED_REPORTS:
                for content_index, journal_content in enumerate(("", " \t\r\n\n")):
                    with self.subTest(
                        report=report_class.__name__,
                        journal_content=repr(journal_content),
                    ):
                        destination = os.path.join(
                            directory,
                            f"empty-{report_class.__name__}."
                            f"{content_index}.{extension}",
                        )
                        report = report_class()
                        report.initiate(destination)
                        report.finish()
                        original_report = Path(destination).read_bytes()
                        Path(report.journal_path(destination)).write_text(
                            journal_content,
                            encoding="utf-8",
                        )

                        with self.assertRaises(FileExistsException):
                            report_class().initiate(destination)

                        self.assertEqual(
                            Path(destination).read_bytes(),
                            original_report,
                        )

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
