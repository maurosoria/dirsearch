from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase

from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.wordlist_config import WordlistConfig
from lib.core.exceptions import WordlistLimitError
from lib.core.settings import ARCHIVE_EXTENSIONS, BACKUP_EXTENSIONS
from lib.core.wordlist_template import DEFAULT_PLACEHOLDERS


class TestDictionaryTemplates(TestCase):
    def setUp(self):
        self._original_options = dict(options)
        options.update(
            {
                "extensions": ("php", "json"),
                "exclude_extensions": (),
                "force_extensions": False,
                "overwrite_extensions": False,
                "prefixes": (),
                "suffixes": (),
                "lowercase": False,
                "uppercase": False,
                "capitalization": False,
                "wordlist_max_size": 500000,
            }
        )

    def tearDown(self):
        options.clear()
        options.update(self._original_options)

    def _dictionary(self, *lines: str) -> Dictionary:
        fd, path = tempfile.mkstemp(prefix="dirsearch-template-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            return Dictionary(WordlistConfig.from_options(options), files=[path])
        finally:
            os.unlink(path)

    def test_subject_placeholder(self):
        dictionary = self._dictionary("list_%SUBJECT%.php")

        self.assertIn("list_user.php", dictionary)
        self.assertIn("list_articles.php", dictionary)

    def test_crud_placeholder(self):
        dictionary = self._dictionary("%CRUD_OP%_articles.php")

        self.assertIn("create_articles.php", dictionary)
        self.assertIn("delete_articles.php", dictionary)

    def test_repeated_placeholder_uses_same_value(self):
        dictionary = self._dictionary("%ENV%/%ENV%.txt")

        self.assertIn("dev/dev.txt", dictionary)
        self.assertIn("prod/prod.txt", dictionary)
        self.assertNotIn("dev/prod.txt", dictionary)

    def test_category_placeholder(self):
        dictionary = self._dictionary("%CATEGORY:keys%.txt")

        self.assertIn("key.pem.txt", dictionary)

    def test_ext_placeholder_compatibility(self):
        dictionary = self._dictionary("index.%EXT%")

        self.assertEqual(list(dictionary), ["index.php", "index.json"])

    def test_archive_placeholder_keeps_historical_values(self):
        dictionary = self._dictionary("backup.%ARCHIVE%")

        self.assertEqual(
            list(dictionary),
            [f"backup.{extension}" for extension in ARCHIVE_EXTENSIONS],
        )

    def test_backup_placeholder_includes_extended_values(self):
        dictionary = self._dictionary("backup.%BACKUP%")

        self.assertEqual(
            list(dictionary),
            [f"backup.{extension}" for extension in BACKUP_EXTENSIONS],
        )

    def test_add_extra_filters_invalid_dynamic_paths(self):
        options["exclude_extensions"] = ("zip",)
        dictionary = Dictionary(WordlistConfig.from_options(options), files=[])

        for path in ("", "#comment", "backup.zip?download=1"):
            dictionary.add_extra(path)
        dictionary.add_extra("admin")

        self.assertEqual(next(dictionary), "admin")
        with self.assertRaises(StopIteration):
            next(dictionary)

    def test_generation_limit(self):
        options["wordlist_max_size"] = 1

        with self.assertRaises(WordlistLimitError):
            self._dictionary("%CRUD_OP%_articles.php")

    def test_wordlist_documentation_lists_all_supported_placeholders(self):
        documentation = (
            Path(__file__).parents[2] / "docs" / "wordlists.md"
        ).read_text(encoding="utf-8")
        placeholders = set(DEFAULT_PLACEHOLDERS) | {
            "EXT",
            "YYYY",
            "YY",
            "MM",
            "DD",
            "DATE",
            "DATE_COMPACT",
        }

        for placeholder in sorted(placeholders):
            with self.subTest(placeholder=placeholder):
                self.assertIn(f"%{placeholder}%", documentation)
        self.assertIn("%CATEGORY:name%", documentation)
