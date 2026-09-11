# -*- coding: utf-8 -*-

import os
import stat
import tempfile
from unittest import TestCase, skipIf, skipUnless
from unittest.mock import patch

from lib.utils.file import FileUtils


class TestFileUtils(TestCase):
    def test_create_private_dir_requests_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = FileUtils.build_path(directory, "session")
            with patch(
                "lib.utils.file.os.makedirs",
                wraps=os.makedirs,
            ) as makedirs:
                FileUtils.create_private_dir(destination)

        makedirs.assert_called_once_with(
            destination,
            mode=0o700,
            exist_ok=True,
        )

    @skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_create_private_dir_rejects_directory_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = FileUtils.build_path(directory, "outside")
            destination = FileUtils.build_path(directory, "session")
            os.mkdir(outside)
            try:
                os.symlink(outside, destination, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(OSError, "Refusing symbolic link"):
                FileUtils.create_private_dir(destination)

            self.assertEqual(os.listdir(outside), [])

    @skipIf(os.name == "nt", "POSIX mode bits are unavailable on Windows")
    def test_private_writes_set_modes_without_changing_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = FileUtils.build_path(directory, "session")
            previous_umask = os.umask(0o000)
            try:
                FileUtils.create_private_dir(destination)
                file_name = FileUtils.build_path(destination, "options.json")
                with FileUtils.atomic_write_private_text(file_name) as file_handle:
                    file_handle.write("first")
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(os.stat(destination).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(file_name).st_mode), 0o600)

            os.chmod(destination, 0o755)
            os.chmod(file_name, 0o644)
            FileUtils.create_private_dir(destination)
            with FileUtils.atomic_write_private_text(file_name) as file_handle:
                file_handle.write("second")

            self.assertEqual(stat.S_IMODE(os.stat(destination).st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(os.stat(file_name).st_mode), 0o600)

    def test_atomic_private_write_preserves_existing_file_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "options.json")
            with open(file_name, "w", encoding="utf-8") as file_handle:
                file_handle.write("preserved")

            with self.assertRaisesRegex(OSError, "write failed"):
                with FileUtils.atomic_write_private_text(file_name) as file_handle:
                    file_handle.write("replacement")
                    raise OSError("write failed")

            with open(file_name, encoding="utf-8") as file_handle:
                self.assertEqual(file_handle.read(), "preserved")
            self.assertEqual(os.listdir(directory), ["options.json"])

    def test_atomic_private_write_cleans_up_after_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "options.json")
            with open(file_name, "w", encoding="utf-8") as file_handle:
                file_handle.write("preserved")

            with patch(
                "lib.utils.file.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    with FileUtils.atomic_write_private_text(file_name) as file_handle:
                        file_handle.write("replacement")

            with open(file_name, encoding="utf-8") as file_handle:
                self.assertEqual(file_handle.read(), "preserved")
            self.assertEqual(os.listdir(directory), ["options.json"])

    @skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_atomic_private_write_replaces_symlink_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "options.json")
            outside = FileUtils.build_path(directory, "outside.json")
            with open(outside, "w", encoding="utf-8") as file_handle:
                file_handle.write("preserved")
            try:
                os.symlink(outside, file_name)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with FileUtils.atomic_write_private_text(file_name) as file_handle:
                file_handle.write("replacement")

            with open(outside, encoding="utf-8") as file_handle:
                self.assertEqual(file_handle.read(), "preserved")
            self.assertFalse(FileUtils.is_link(file_name))
            with open(file_name, encoding="utf-8") as file_handle:
                self.assertEqual(file_handle.read(), "replacement")

    def test_create_writable_dir_creates_and_validates_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = FileUtils.build_path(directory, "responses")

            FileUtils.create_writable_dir(destination)

            self.assertTrue(FileUtils.is_dir(destination))
            self.assertEqual(os.listdir(destination), [])

    def test_create_writable_dir_rejects_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = FileUtils.build_path(directory, "responses")
            with open(destination, "wb"):
                pass

            with self.assertRaises((FileExistsError, NotADirectoryError)):
                FileUtils.create_writable_dir(destination)

    def test_create_writable_dir_propagates_probe_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "lib.utils.file.tempfile.mkstemp",
                side_effect=PermissionError("read-only"),
            ):
                with self.assertRaisesRegex(PermissionError, "read-only"):
                    FileUtils.create_writable_dir(directory)

    def test_open_exclusive_never_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "response")
            descriptor = FileUtils.open_exclusive(file_name)
            with os.fdopen(descriptor, "wb") as file_handle:
                file_handle.write(b"original")

            with self.assertRaises(FileExistsError):
                FileUtils.open_exclusive(file_name)

            self.assertEqual(FileUtils.read_bytes(file_name), b"original")

    def test_open_binary_append_preserves_existing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "responses.jsonl")
            for body in (b"first", b"second"):
                descriptor = FileUtils.open_binary_append(file_name)
                with os.fdopen(descriptor, "ab", buffering=0) as file_handle:
                    file_handle.write(body)

            self.assertEqual(FileUtils.read_bytes(file_name), b"firstsecond")

    def test_private_text_append_preserves_existing_text(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "report.txt")

            FileUtils.append_private_text(file_name, "first\n")
            FileUtils.append_private_text(file_name, "second\n")

            self.assertEqual(
                FileUtils.read_bytes(file_name),
                f"first{os.linesep}second{os.linesep}".encode(),
            )

    @skipIf(os.name == "nt", "POSIX mode bits are unavailable on Windows")
    def test_private_text_append_creates_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "report.txt")
            previous_umask = os.umask(0o000)
            try:
                FileUtils.append_private_text(file_name, "result\n")
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(os.stat(file_name).st_mode), 0o600)

    @skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_open_binary_append_does_not_follow_symbolic_link(self):
        with tempfile.TemporaryDirectory() as directory:
            file_name = FileUtils.build_path(directory, "responses.jsonl")
            outside = FileUtils.build_path(directory, "outside.jsonl")
            try:
                os.symlink(outside, file_name)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with self.assertRaises(OSError):
                FileUtils.open_binary_append(file_name)

            self.assertFalse(FileUtils.exists(outside))
