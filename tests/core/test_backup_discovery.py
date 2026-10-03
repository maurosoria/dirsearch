from unittest import TestCase
from unittest.mock import patch

from lib.connection.response import NativeResponse
from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.dictionary import Dictionary
from lib.core.wordlist_config import WordlistConfig
from lib.core.settings import ARCHIVE_EXTENSIONS, BACKUP_EXTENSIONS
from lib.core.wordlist_template import generate_backup_paths


def make_dictionary() -> Dictionary:
    dictionary = Dictionary(WordlistConfig.from_options(options))
    dictionary.__setstate__(([], 0, [], 0))
    return dictionary


def response_for(path: str) -> NativeResponse:
    return NativeResponse(
        f"https://example.com/{path}",
        200,
        [("content-type", "text/plain")],
        b"found",
    )


class TestBackupPathGeneration(TestCase):
    def test_generates_full_filename_and_basename_variants(self):
        paths = list(generate_backup_paths("assets/test.php"))

        self.assertEqual(paths[0], "assets/test.php~")
        for extension in BACKUP_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertIn(f"assets/test.php.{extension}", paths)
        for extension in ARCHIVE_EXTENSIONS:
            with self.subTest(archive_extension=extension):
                self.assertIn(f"assets/test.{extension}", paths)
        for extension in set(BACKUP_EXTENSIONS) - set(ARCHIVE_EXTENSIONS):
            with self.subTest(backup_extension=extension):
                self.assertNotIn(f"assets/test.{extension}", paths)
        self.assertEqual(len(paths), len(set(paths)))

    def test_generates_backups_for_configuration_files(self):
        paths = list(generate_backup_paths("config.yml"))

        self.assertIn("config.yml.bak", paths)
        self.assertIn("config.bak", paths)

    def test_skips_media_and_existing_backups_case_insensitively(self):
        for path in (
            "photo.JPEG",
            "archive.BAK",
            "backup.TAR.GZ",
            "index.php~",
        ):
            with self.subTest(path=path):
                self.assertEqual(list(generate_backup_paths(path)), [])

    def test_extension_matching_requires_a_dot_boundary(self):
        self.assertIn("foo.cold.bak", generate_backup_paths("foo.cold"))

    def test_skips_directories_and_extensionless_paths(self):
        for path in ("admin/", "README"):
            with self.subTest(path=path):
                self.assertEqual(list(generate_backup_paths(path)), [])

    def test_dotfiles_only_get_full_filename_variants(self):
        paths = list(generate_backup_paths(".env"))

        self.assertIn(".env~", paths)
        self.assertIn(".env.bak", paths)
        self.assertNotIn(".bak", paths)


class TestBackupDiscoveryCallback(TestCase):
    def setUp(self):
        self._original_options = dict(options)
        options.update(
            {
                "find_backup": True,
                "skip_on_status": set(),
                "full_url": False,
                "recursion_status_codes": set(),
                "recursive": False,
                "deep_recursive": False,
                "force_recursive": False,
                "replay_proxy": None,
                "crawl": False,
                "exclude_extensions": (),
            }
        )

    def tearDown(self):
        options.clear()
        options.update(self._original_options)

    def _controller(self) -> Controller:
        controller = object.__new__(Controller)
        controller.execution_config = ExecutionConfig()
        controller.discovery_config = DiscoveryConfig.from_options(options)
        controller.base_path = "app/"
        controller.dictionary = make_dictionary()
        return controller

    def test_adds_generated_candidates_to_shared_dictionary(self):
        controller = self._controller()

        with patch("lib.controller.controller.interface.status_report"):
            controller.match_callback(response_for("app/test.php"))

        self.assertIn("test.php.bak", controller.dictionary._extra)
        self.assertIn("test.bak", controller.dictionary._extra)
        self.assertIn("test.php~", controller.dictionary._extra)

    def test_honors_excluded_extensions_for_dynamic_candidates(self):
        options["exclude_extensions"] = ("bak", "zip")
        controller = self._controller()

        with patch("lib.controller.controller.interface.status_report"):
            controller.match_callback(response_for("app/test.php"))

        self.assertTrue(controller.dictionary._extra)
        self.assertFalse(
            any(
                path.endswith((".bak", ".zip"))
                for path in controller.dictionary._extra
            )
        )
