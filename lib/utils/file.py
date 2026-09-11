# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from __future__ import annotations

from contextlib import contextmanager
import os
import os.path
import tempfile


class File:
    def __init__(self, *path_components):
        self._path = FileUtils.build_path(*path_components)

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, value):
        raise NotImplementedError

    def is_valid(self):
        return FileUtils.is_file(self.path)

    def exists(self):
        return FileUtils.exists(self.path)

    def can_read(self):
        return FileUtils.can_read(self.path)

    def can_write(self):
        return FileUtils.can_write(self.path)

    def read(self):
        return FileUtils.read(self.path)

    def get_lines(self):
        return FileUtils.get_lines(self.path)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        pass


class FileUtils:
    @staticmethod
    def build_path(*path_components: str) -> str:
        if path_components:
            path = os.path.join(*path_components)
        else:
            path = ""

        return path

    @staticmethod
    def get_abs_path(file_name):
        return os.path.abspath(file_name)

    @staticmethod
    def exists(file_name):
        return os.access(file_name, os.F_OK)

    @staticmethod
    def is_empty(file_name):
        return os.stat(file_name).st_size == 0

    @staticmethod
    def can_read(file_name):
        try:
            with open(file_name):
                pass
        except OSError:
            return False

        return True

    @classmethod
    def can_write(cls, path):
        while not cls.exists(path):
            path = cls.parent(path)

        return os.access(path, os.W_OK)

    @staticmethod
    def read(file_name):
        return open(file_name, "r").read()

    @staticmethod
    def read_bytes(file_name):
        with open(file_name, "rb") as fd:
            return fd.read()

    @classmethod
    def get_files(cls, directory):
        files = []

        for path in os.listdir(directory):
            path = os.path.join(directory, path)
            if cls.is_dir(path):
                files.extend(cls.get_files(path))
            else:
                files.append(path)

        return files

    @staticmethod
    def get_lines(file_name: str) -> list[str]:
        with open(file_name, "r", errors="replace") as fd:
            return fd.read().splitlines()

    @staticmethod
    def is_dir(path):
        return os.path.isdir(path)

    @staticmethod
    def is_file(path):
        return os.path.isfile(path)

    @staticmethod
    def is_link(path):
        return os.path.islink(path)

    @staticmethod
    def parent(path, depth=1):
        for _ in range(depth):
            path = os.path.dirname(path)

        return path

    @classmethod
    def create_dir(cls, directory):
        if not cls.exists(directory):
            os.makedirs(directory, exist_ok=True)

    @staticmethod
    def create_private_dir(directory: str) -> None:
        """Create a private leaf directory without following a leaf link."""
        if os.path.islink(directory):
            raise OSError(f"Refusing symbolic link: {directory}")
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.path.islink(directory):
            raise OSError(f"Refusing symbolic link: {directory}")

    @classmethod
    def create_writable_dir(cls, directory: str) -> None:
        """Create a directory and prove that files can be created inside it."""
        cls.create_dir(directory)
        if not cls.is_dir(directory):
            raise NotADirectoryError(f"Not a directory: {directory}")

        descriptor, probe_path = tempfile.mkstemp(
            prefix=".dirsearch-write-test-",
            dir=directory,
        )
        os.close(descriptor)
        cls.remove(probe_path)

    @classmethod
    def open_binary_append(cls, file_name: str) -> int:
        """Open a binary file descriptor for append without following links."""
        if cls.is_link(file_name):
            raise OSError(f"Refusing symbolic link: {file_name}")

        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        return os.open(file_name, flags, 0o600)

    @staticmethod
    def open_exclusive(file_name: str) -> int:
        """Create a private binary file without replacing or following a path."""
        if os.name == "nt":
            return FileUtils._open_exclusive_windows(file_name)

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        return os.open(file_name, flags, 0o600)

    @staticmethod
    @contextmanager
    def atomic_write_private_text(
        file_name: str,
        encoding: str | None = "utf-8",
    ):
        """Write text through a private same-directory replacement file."""
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(file_name)}.",
            suffix=".tmp",
            dir=FileUtils.parent(file_name),
        )
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding=encoding) as file_handle:
                descriptor = -1
                yield file_handle
            os.replace(temporary_path, file_name)
        finally:
            if descriptor != -1:
                os.close(descriptor)
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def _open_exclusive_windows(file_name: str) -> int:
        """Create a Windows file without following an existing reparse point."""
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        generic_write = 0x40000000
        create_new = 1
        file_attribute_normal = 0x00000080
        file_flag_open_reparse_point = 0x00200000
        invalid_handle = ctypes.c_void_p(-1).value
        original_path = FileUtils.get_abs_path(file_name)
        absolute_path = original_path
        if not absolute_path.startswith("\\\\?\\"):
            if absolute_path.startswith("\\\\"):
                absolute_path = "\\\\?\\UNC\\" + absolute_path[2:]
            else:
                absolute_path = "\\\\?\\" + absolute_path

        handle = create_file(
            absolute_path,
            generic_write,
            0,
            None,
            create_new,
            file_attribute_normal | file_flag_open_reparse_point,
            None,
        )
        if handle == invalid_handle:
            error_code = ctypes.get_last_error()
            if error_code in (80, 183):
                raise FileExistsError(
                    error_code,
                    "File already exists",
                    original_path,
                )
            raise OSError(error_code, ctypes.FormatError(error_code), original_path)

        try:
            return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
        except Exception:
            close_handle(handle)
            raise

    @staticmethod
    def remove(file_name: str) -> None:
        os.unlink(file_name)

    @staticmethod
    def write_lines(file_name, lines, overwrite=False):
        if isinstance(lines, list):
            lines = os.linesep.join(lines)
        with open(file_name, "w" if overwrite else "a") as f:
            f.writelines(lines)
