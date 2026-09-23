import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import call, patch

from lib.report.factory import SQLReportMixin
from lib.report.sqlite_report import SQLiteReport


def make_result(url):
    return SimpleNamespace(
        datetime="2026-09-05 23:30:00",
        url=url,
        status=200,
        length=42,
        type="text/plain",
        redirect="",
    )


class TestSQLReportPersistence(TestCase):
    def test_sqlite_report_reuses_one_connection_for_multiple_results(self):
        with TemporaryDirectory() as directory:
            database = str(Path(directory, "report.sqlite"))
            report = SQLiteReport()

            with patch.object(report, "connect", wraps=report.connect) as connect:
                report.initiate(database, "results")
                report.save(database, "results", make_result("https://one.example/"))
                report.save(database, "results", make_result("https://two.example/"))
                report.finish()

            self.assertEqual(connect.call_args_list, [call(database)])
            self.assertIsNone(report._conn)
            self.assertIsNone(report._conn_database)

            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute(
                    'SELECT url FROM "results" ORDER BY rowid'
                ).fetchall()

        self.assertEqual(
            rows,
            [("https://one.example/",), ("https://two.example/",)],
        )

    def test_sqlite_report_switches_connections_for_formatted_destinations(self):
        with TemporaryDirectory() as directory:
            first_database = str(Path(directory, "first.sqlite"))
            second_database = str(Path(directory, "second.sqlite"))
            report = SQLiteReport()

            with patch.object(report, "connect", wraps=report.connect) as connect:
                report.initiate(first_database, "results")
                report.save(
                    first_database,
                    "results",
                    make_result("https://one.example/"),
                )
                report.initiate(second_database, "results")
                report.save(
                    second_database,
                    "results",
                    make_result("https://two.example/"),
                )
                report.finish()

            self.assertEqual(
                connect.call_args_list,
                [call(first_database), call(second_database)],
            )
            self.assertIsNone(report._conn)
            self.assertIsNone(report._conn_database)

            with closing(sqlite3.connect(first_database)) as connection:
                first_rows = connection.execute(
                    'SELECT url FROM "results" ORDER BY rowid'
                ).fetchall()
            with closing(sqlite3.connect(second_database)) as connection:
                second_rows = connection.execute(
                    'SELECT url FROM "results" ORDER BY rowid'
                ).fetchall()

        self.assertEqual(first_rows, [("https://one.example/",)])
        self.assertEqual(second_rows, [("https://two.example/",)])

    def test_reinitializing_sqlite_table_preserves_existing_results(self):
        with TemporaryDirectory() as directory:
            database = str(Path(directory, "report.sqlite"))
            report = SQLiteReport()
            report.initiate(database, "results")
            report.save(database, "results", make_result("https://one.example/"))

            report.initiate(database, "results")
            second_report = SQLiteReport()
            second_report.initiate(database, "results")
            second_report.finish()
            report.finish()

            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute(
                    'SELECT url FROM "results" ORDER BY rowid'
                ).fetchall()

        self.assertEqual(rows, [("https://one.example/",)])

    def test_new_sqlite_table_keeps_existing_schema_and_accepts_results(self):
        with TemporaryDirectory() as directory:
            database = str(Path(directory, "report.sqlite"))
            report = SQLiteReport()
            report.initiate(database, "results")
            report.save(database, "results", make_result("https://example.test/"))
            report.finish()

            with closing(sqlite3.connect(database)) as connection:
                columns = [
                    row[1]
                    for row in connection.execute('PRAGMA table_info("results")')
                ]
                row = connection.execute(
                    'SELECT url, status_code, content_length FROM "results"'
                ).fetchone()

        self.assertEqual(
            columns,
            [
                "time",
                "url",
                "status_code",
                "content_length",
                "content_type",
                "redirect",
            ],
        )
        self.assertEqual(row, ("https://example.test/", 200, 42))

    def test_incompatible_existing_sqlite_table_is_not_modified(self):
        with TemporaryDirectory() as directory:
            database = str(Path(directory, "report.sqlite"))
            with closing(sqlite3.connect(database)) as connection:
                connection.execute('CREATE TABLE "results" (sentinel TEXT)')
                connection.execute('INSERT INTO "results" VALUES (?)', ("keep-me",))
                connection.commit()

            report = SQLiteReport()
            report.initiate(database, "results")
            report.finish()

            with closing(sqlite3.connect(database)) as connection:
                columns = [
                    row[1]
                    for row in connection.execute('PRAGMA table_info("results")')
                ]
                rows = connection.execute('SELECT sentinel FROM "results"').fetchall()

        self.assertEqual(columns, ["sentinel"])
        self.assertEqual(rows, [("keep-me",)])

    def test_all_sql_create_queries_are_idempotent(self):
        shared_query = SQLReportMixin.get_create_table_query(None, "results")[0]
        sqlite_query = SQLiteReport().get_create_table_query("results")[0]

        for query in (shared_query, sqlite_query):
            with self.subTest(query=query):
                self.assertIn("CREATE TABLE IF NOT EXISTS", query)
                self.assertNotIn("DROP TABLE", query)
