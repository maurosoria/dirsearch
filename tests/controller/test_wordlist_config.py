import os
import tempfile
from unittest import TestCase
from unittest.mock import patch

from lib.controller.controller import Controller
from lib.controller.session import SessionStore
from lib.core.data import options
from lib.core.dictionary import Dictionary


class TestControllerWordlistConfig(TestCase):
    def test_setup_snapshots_wordlist_policy_for_each_request_stack(self):
        for backend, async_mode in (("python", False), ("python", True), ("native", False)):
            with (
                self.subTest(backend=backend, async_mode=async_mode),
                patch.dict(options, {
                    "request_backend": backend, "async_mode": async_mode,
                    "wordlist_backend": "python", "session_file": None,
                    "wordlists": ["fixture"], "extensions": ("html",),
                    "exclude_extensions": ("zip",), "force_extensions": False,
                    "overwrite_extensions": False, "prefixes": (), "suffixes": (),
                    "lowercase": False, "uppercase": False, "capitalization": False,
                    "raw_file": None, "log_file": None,
                }),
                patch.object(Controller, "run"),
                patch.object(Controller, "_prepare_response_stores"),
                patch("lib.controller.controller.create_terminal"),
                patch("lib.controller.controller.ReportManager"),
                patch("lib.core.wordlist_backend.FileUtils.get_lines", return_value=["page.%EXT%"]),
            ):
                controller = Controller()
                config = controller.wordlist_config
                options["extensions"] = ("json",)
                options["exclude_extensions"] = ("html",)
                self.assertIs(controller.dictionary.config, config)
                self.assertEqual(config.native_corpus, backend == "native")
                self.assertEqual(list(controller.dictionary), ["page.html"])
                self.assertFalse(controller.dictionary.is_valid("archive.zip"))
                self.assertTrue(controller.dictionary.is_valid("other.html"))

    def test_import_rebuilds_policy_but_never_regenerates_saved_words(self):
        for backend, async_mode in (("python", False), ("python", True), ("native", False)):
            with (
                self.subTest(backend=backend, async_mode=async_mode),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(options, {
                    "request_backend": backend, "async_mode": async_mode,
                    "wordlist_backend": "python", "session_file": None,
                    "wordlists": ["fixture"], "extensions": ("html",),
                    "exclude_extensions": ("zip",), "wordlist_max_size": 100,
                    "force_extensions": False, "overwrite_extensions": False,
                    "prefixes": (), "suffixes": (), "lowercase": False,
                    "uppercase": False, "capitalization": False,
                    "raw_file": None, "log_file": None, "output_formats": [],
                }),
                patch.object(Controller, "run"),
                patch.object(Controller, "_prepare_response_stores"),
                patch.object(Controller, "_confirm_session_overwrite"),
                patch("lib.controller.controller.create_terminal"),
                patch("lib.controller.controller.ReportManager"),
                patch("lib.core.wordlist_backend.FileUtils.get_lines", return_value=["done", "pending"]),
            ):
                original = Controller()
                original.run_state.prepare_targets(options["urls"])
                original.target_progress.base_path = ""
                original.target_progress.url = "http://example.test/"
                self.assertEqual(next(original.dictionary), "done")
                self.assertEqual(original.dictionary.claim_next(), "pending")
                original.dictionary.add_extra("dynamic.html")
                # Resume uses the checkpoint, even if source files are gone or
                # its saved generation limit is below the existing corpus size.
                options["wordlists"] = [os.path.join(directory, "absent.txt")]
                options["wordlist_max_size"] = 1
                checkpoint = os.path.join(directory, "session")
                store = SessionStore()
                store.save(original._snapshot_session(options, ""), checkpoint)
                payload = store.load(checkpoint)
                self.assertEqual(payload.task_checkpoint.dictionary.to_state(), (
                    ["done", "pending"], 2, ["pending", "dynamic.html"], 0,
                ))
                options.update(
                    session_file=checkpoint, extensions=("json",),
                    exclude_extensions=("html",), request_backend="python",
                )
                with patch.object(Dictionary, "generate", side_effect=AssertionError("regenerated")):
                    resumed = Controller()
                config = resumed.wordlist_config
                self.assertIs(resumed.dictionary.config, config)
                self.assertIsNot(config, original.wordlist_config)
                self.assertEqual(config.extensions, ("html",))
                self.assertEqual(config.exclude_extensions, ("zip",))
                self.assertEqual(config.native_corpus, backend == "native")
                self.assertEqual(config.max_size, 1)
                options["exclude_extensions"] = ("html",)
                resumed.dictionary.add_extra("archive.zip")
                self.assertEqual(resumed.dictionary.claim_many(10), ["pending", "dynamic.html"])
                resumed.dictionary.reset()
                self.assertEqual(resumed.dictionary.claim_many(10), ["done", "pending"])
