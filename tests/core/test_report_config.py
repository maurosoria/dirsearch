from dataclasses import FrozenInstanceError
from unittest import TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.core.report_config import ReportConfig


class TestReportConfig(TestCase):
    def test_snapshot_uses_only_supplied_options_and_detaches_formats(self):
        formats = ["json", "sqlite"]
        values = {
            "output_formats": formats,
            "output_file": "report-{host}.{extension}",
            "output_table": "results",
            "mysql_url": "mysql://user:secret@example.test/db",
            "postgres_url": "postgresql://user:secret@example.test/db",
            "sqlite_commit_batch_size": 25,
        }
        with patch.dict(options, {}, clear=True):
            config = ReportConfig.from_options(values)
        formats.clear()
        values.update(output_file="changed", output_table="other", sqlite_commit_batch_size=1)
        self.assertEqual(config, ReportConfig(
            formats=("json", "sqlite"), output_file="report-{host}.{extension}",
            output_table="results", mysql_url="mysql://user:secret@example.test/db",
            postgres_url="postgresql://user:secret@example.test/db", sqlite_commit_batch_size=25,
        ))
        with self.assertRaises(FrozenInstanceError):
            config.output_file = "changed"

    def test_manual_config_copies_format_list_preserving_order(self):
        formats = ["sqlite", "json"]
        config = ReportConfig(formats=formats)
        formats.reverse()
        self.assertEqual(config.formats, ("sqlite", "json"))
        self.assertEqual(ReportConfig().formats, ())

    def test_unset_formats_are_disabled(self):
        for formats in (None, [], ()):
            with self.subTest(formats=formats):
                config = ReportConfig.from_options({
                    "output_formats": formats, "output_file": None,
                    "output_table": None, "mysql_url": None,
                    "postgres_url": None, "sqlite_commit_batch_size": 1,
                })
                self.assertEqual(config, ReportConfig())

    def test_database_urls_are_not_exposed_in_repr(self):
        config = ReportConfig(
            mysql_url="mysql://user:mysql-secret@example.test/db",
            postgres_url="postgresql://user:postgres-secret@example.test/db",
        )
        self.assertNotIn("mysql-secret", repr(config))
        self.assertNotIn("postgres-secret", repr(config))
        self.assertNotIn("example.test", repr(config))
