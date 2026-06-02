import os
import sys
import tempfile
import unittest
import sqlite3

# dirsearch uses relative imports; add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCSVReportExceptions(unittest.TestCase):
    """Verify CSV report raises domain-specific exceptions on invalid input."""

    def setUp(self):
        from lib.report.csv_report import CSVReport
        self.report = CSVReport()

    def test_header_mismatch_raises_valueerror(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("Wrong,Header,Format\n")
            f.write("data,200,100,text/html,,0.1\n")
            csv_path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                self.report.parse(csv_path)
            self.assertIn("CSV header mismatch", str(ctx.exception))
        finally:
            os.unlink(csv_path)

    def test_valid_csv_parses_correctly(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("URL,Status,Size,Content Type,Redirection,Elapsed (s)\n")
            f.write("https://example.com,200,1234,text/html,,0.05\n")
            csv_path = f.name
        try:
            rows = self.report.parse(csv_path)
            self.assertEqual(len(rows), 2)
        finally:
            os.unlink(csv_path)


class TestSQLiteReportExceptions(unittest.TestCase):
    """Verify SQLite report raises domain-specific exceptions on invalid input."""

    def setUp(self):
        from lib.report.sqlite_report import SQLiteReport
        self.report = SQLiteReport()

    def test_corrupt_file_raises_databaseerror(self):
        db_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".db", delete=False
            ) as f:
                f.write("this is not a sqlite database file\n")
                db_path = f.name
            with self.assertRaises(sqlite3.DatabaseError) as ctx:
                self.report.connect(db_path)
            self.assertIn("not a valid SQLite database", str(ctx.exception))
        finally:
            if db_path:
                try:
                    os.unlink(db_path)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
