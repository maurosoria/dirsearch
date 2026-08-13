from __future__ import annotations

import os
import tempfile
from unittest import TestCase

from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import WordlistLimitError


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
            return Dictionary(files=[path])
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

    def test_is_valid_filters_invalid_crawled_paths(self):
        options["exclude_extensions"] = ("zip",)
        dictionary = Dictionary(files=[])

        self.assertTrue(dictionary.is_valid("admin"))
        self.assertFalse(dictionary.is_valid(""))
        self.assertFalse(dictionary.is_valid("#comment"))
        self.assertFalse(dictionary.is_valid("backup.zip?download=1"))

    def test_generation_limit(self):
        options["wordlist_max_size"] = 1

        with self.assertRaises(WordlistLimitError):
            self._dictionary("%CRUD_OP%_articles.php")
