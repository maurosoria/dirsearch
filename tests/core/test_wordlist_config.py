from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.core.data import options
from lib.core.dictionary import Dictionary, get_blacklists
from lib.core.exceptions import WordlistBackendUnavailableError, WordlistLimitError
from lib.core.native_runtime import NATIVE_EXTENSION_VERSION
from lib.core.settings import EXCLUDE_OVERWRITE_EXTENSIONS
from lib.core.wordlist_backend import (
    NativeWordlistBackend,
    NativeWordlistCorpus,
    PythonWordlistBackend,
    get_wordlist_backend,
)
from lib.core.wordlist_config import WordlistConfig
from tests.core.test_wordlist_backend import FakeOwnedWordlist


class TestWordlistConfig(TestCase):
    def test_collections_are_frozen_without_reordering_or_deduplicating(self):
        values = ["", "html", "html"]
        config = WordlistConfig(
            extensions=values, exclude_extensions=values,
            prefixes=values, suffixes=values,
        )
        values.clear()
        self.assertEqual(config.extensions, ("", "html", "html"))
        self.assertEqual(config.exclude_extensions, config.extensions)
        self.assertEqual(config.prefixes, config.extensions)
        self.assertEqual(config.suffixes, config.extensions)
        with self.assertRaises(FrozenInstanceError):
            config.max_size = 1

    def test_adapter_copies_every_wordlist_option_from_supplied_mapping(self):
        values = {
            "wordlist_backend": "native", "request_backend": "native",
            "extensions": ["html"], "exclude_extensions": ["zip"],
            "prefixes": ["pre-"], "suffixes": ["-end"],
            "force_extensions": True, "overwrite_extensions": True,
            "lowercase": True, "uppercase": True, "capitalization": True,
            "wordlist_max_size": 25,
        }
        with patch.dict(options, {}, clear=True):
            config = WordlistConfig.from_options(values)
        values["extensions"].clear()
        self.assertEqual(config, WordlistConfig(
            backend="native", native_corpus=True,
            extensions=("html",), exclude_extensions=("zip",),
            prefixes=("pre-",), suffixes=("-end",),
            force_extensions=True, overwrite_extensions=True,
            lowercase=True, uppercase=True, capitalization=True, max_size=25,
        ))

    def test_two_generators_keep_independent_policy_without_global_options(self):
        first = PythonWordlistBackend(WordlistConfig(
            extensions=("html",), exclude_extensions=("zip",), lowercase=True,
        ))
        second = PythonWordlistBackend(WordlistConfig(
            extensions=("json",), exclude_extensions=("txt",), uppercase=True,
        ))
        with (
            patch.dict(options, {}, clear=True),
            patch("lib.core.wordlist_backend.FileUtils.get_lines", return_value=[
                "Page.%EXT%", "sample.txt", "archive.zip",
            ]),
        ):
            self.assertEqual(first.generate(["fixture"]), ["page.html", "sample.txt"])
            self.assertEqual(second.generate(["fixture"]), ["PAGE.JSON", "ARCHIVE.ZIP"])
            self.assertEqual(first.generate(["fixture"]), ["page.html", "sample.txt"])

    def test_dynamic_validation_and_reset_keep_dictionary_policy(self):
        config = WordlistConfig(exclude_extensions=["zip"])
        dictionary = Dictionary(config)
        other = Dictionary(WordlistConfig(exclude_extensions=["txt"]))
        with patch.dict(options, {}, clear=True):
            for current in (dictionary, other):
                current.add_extra("archive.zip?download=1")
                current.add_extra("file.txt#section")
            self.assertEqual(next(dictionary), "file.txt#section")
            self.assertEqual(next(other), "archive.zip?download=1")
            dictionary.reset()
            dictionary.add_extra("archive.zip")
            dictionary.add_extra("fresh.txt")
            self.assertEqual(next(dictionary), "fresh.txt")
            with self.assertRaises(StopIteration):
                next(dictionary)
        self.assertIs(dictionary.config, config)

    def test_blacklists_share_policy_but_skip_generation_variants(self):
        config = WordlistConfig(
            extensions=("html",), force_extensions=True,
            prefixes=("pre-",), suffixes=("-end",), lowercase=True,
            exclude_extensions=("zip",),
        )
        with (
            patch.dict(options, {}, clear=True),
            patch("lib.core.dictionary.FileUtils.can_read", return_value=True),
            patch("lib.core.wordlist_backend.FileUtils.get_lines", return_value=[
                "Page.%EXT%", "Archive.zip", "Plain",
            ]),
        ):
            blacklists = get_blacklists(config)
        self.assertEqual(set(blacklists), {400, 403, 500})
        for dictionary in blacklists.values():
            self.assertIs(dictionary.config, config)
            self.assertEqual(list(dictionary), ["page.html", "plain"])

    def test_generation_limit_belongs_to_each_generator(self):
        limited = PythonWordlistBackend(WordlistConfig(max_size=1))
        unlimited = PythonWordlistBackend(WordlistConfig(max_size=0))
        with (
            patch.dict(options, {}, clear=True),
            patch("lib.core.wordlist_backend.FileUtils.get_lines", return_value=["one", "two"]),
        ):
            with self.assertRaisesRegex(WordlistLimitError, r"max-size \(1\)"):
                limited.generate(["fixture"])
            self.assertEqual(unlimited.generate(["fixture"]), ["one", "two"])

    def test_native_receives_snapshot_and_preserves_corpus_ownership(self):
        config = WordlistConfig(
            backend="native", native_corpus=True, extensions=("html",),
            exclude_extensions=("zip",), prefixes=("pre-",), suffixes=("-end",),
            force_extensions=True, overwrite_extensions=True,
            lowercase=True, uppercase=True, capitalization=True, max_size=25,
        )
        storage = FakeOwnedWordlist(["page.html"])
        native = SimpleNamespace(
            __version__=NATIVE_EXTENSION_VERSION,
            generate_wordlist_owned=Mock(return_value=storage),
            generate_wordlist=Mock(return_value=["page.html"]),
        )
        with (
            patch.dict("sys.modules", {"dirsearch_native": native}),
            patch.object(NativeWordlistBackend, "_requires_python_template_expansion", return_value=False),
            patch.dict(options, {}, clear=True),
        ):
            backend = get_wordlist_backend(config)
            corpus = backend.generate(["fixture"])
            self.assertIsInstance(corpus, NativeWordlistCorpus)
            self.assertIs(corpus.native, storage)
            native.generate_wordlist.assert_not_called()
            native.generate_wordlist_owned.assert_called_once_with(
                ["fixture"], ["html"], force_extensions=True,
                prefixes=["pre-"], suffixes=["-end"], exclude_extensions=["zip"],
                overwrite_exclude_extensions=list(EXCLUDE_OVERWRITE_EXTENSIONS),
                lowercase=True, uppercase=True, capitalization=True,
                overwrite_extensions=True, max_size=25,
            )
            python_corpus_backend = get_wordlist_backend(replace(config, native_corpus=False))
            self.assertEqual(python_corpus_backend.generate(["fixture"]), ["page.html"])
            self.assertEqual(native.generate_wordlist_owned.call_count, 1)
            native.generate_wordlist.assert_called_once()

    def test_native_python_expansion_keeps_the_same_config(self):
        config = WordlistConfig(native_corpus=True, extensions=("html",), lowercase=True)
        native = SimpleNamespace(__version__=NATIVE_EXTENSION_VERSION)
        for blacklist in (False, True):
            with (
                self.subTest(blacklist=blacklist),
                patch.dict("sys.modules", {"dirsearch_native": native}),
                patch.object(NativeWordlistBackend, "_requires_python_template_expansion", return_value=True),
                patch("lib.core.wordlist_backend.FileUtils.get_lines", return_value=["Page.%EXT%"]),
                patch.dict(options, {}, clear=True),
            ):
                backend = NativeWordlistBackend(config)
                self.assertEqual(backend.generate(["fixture"], is_blacklist=blacklist), ["page.html"])

    def test_backend_selection_preserves_optional_native_error_contract(self):
        with (
            patch.dict("sys.modules", {"dirsearch_native": None}),
            patch.dict(options, {}, clear=True),
        ):
            config = WordlistConfig(native_corpus=True)
            for policy in (config, replace(config, backend="python")):
                self.assertIsInstance(get_wordlist_backend(policy), PythonWordlistBackend)
            with self.assertRaises(WordlistBackendUnavailableError):
                get_wordlist_backend(replace(config, backend="native"))
            with self.assertRaisesRegex(ValueError, "Unknown wordlist backend"):
                get_wordlist_backend(replace(config, backend="unknown"))
