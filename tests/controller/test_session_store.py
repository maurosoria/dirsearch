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

import json
import os
import stat
import tempfile
from types import SimpleNamespace
from unittest import TestCase, skipIf

from lib.controller.session import SessionStore
from lib.core.dictionary import Dictionary
from lib.core.exceptions import UnpicklingError


class TestSessionStore(TestCase):
    def _write_json(self, path: str, payload: dict) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def _write_session_dir(self, session_dir: str, url: str) -> None:
        os.makedirs(session_dir, exist_ok=True)
        self._write_json(
            os.path.join(session_dir, SessionStore.FILES["meta"]),
            {"version": SessionStore.SESSION_VERSION},
        )
        self._write_json(
            os.path.join(session_dir, SessionStore.FILES["controller"]),
            {"url": url, "directories": [], "jobs_processed": 1, "errors": 0},
        )
        self._write_json(
            os.path.join(session_dir, SessionStore.FILES["options"]),
            {"urls": ["https://example.com"]},
        )

    def _write_session_file(self, session_file: str, url: str) -> None:
        payload = {
            "version": SessionStore.SESSION_VERSION,
            "controller": {"url": url, "directories": [], "jobs_processed": 2, "errors": 0},
            "dictionary": {"items": [], "index": 0, "extra": [], "extra_index": 0},
            "options": {"urls": ["https://example.com"]},
        }
        self._write_json(session_file, payload)

    def _controller(self) -> SimpleNamespace:
        return SimpleNamespace(
            start_time="2026-01-01T00:00:00Z",
            passed_urls=set(),
            directories=[],
            jobs_processed=0,
            errors=0,
            consecutive_errors=0,
            base_path="",
            url="https://example.com/",
            old_session=False,
            dictionary=Dictionary(),
            output_history=[],
        )

    def test_list_sessions_recurses_and_includes_root_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = os.path.join(tmpdir, "2024-01-01", "session_01")
            self._write_session_dir(nested_dir, "https://nested.example.com")

            root_file = os.path.join(tmpdir, "session_root.json")
            self._write_session_file(root_file, "https://root.example.com")

            sessions = SessionStore({}).list_sessions(tmpdir)

            self.assertEqual(len(sessions), 2)
            self.assertEqual(
                [session["path"] for session in sessions],
                sorted([nested_dir, root_file]),
            )

    def test_request_body_bytes_round_trip_through_json_session(self):
        body = "value=\u00e9&currency=\u20ac\r\n".encode("cp1252")
        session_options = {"data": body, "output_formats": []}
        controller = self._controller()

        with tempfile.TemporaryDirectory() as session_dir:
            store = SessionStore(session_options)
            store.save(controller, session_dir, "")
            payload = store.load(session_dir)
            restored = store.restore_options(payload["options"])

        self.assertEqual(restored["data"], body)

    def test_resume_preserves_later_jobs_and_targets_with_full_wordlist(self):
        target_urls = ["https://first.example/", "https://second.example/"]
        session_options = {
            "urls": target_urls,
            "output_formats": [],
        }
        controller = self._controller()
        controller.directories = ["current/", "next/"]
        controller.jobs_processed = 3
        controller.dictionary = object.__new__(Dictionary)
        controller.dictionary.__setstate__(
            (["done", "in-flight", "later"], 1, [], 0)
        )
        self.assertEqual(controller.dictionary.claim_next(), "in-flight")

        with tempfile.TemporaryDirectory() as session_dir:
            store = SessionStore(session_options)
            store.save(controller, session_dir, "")
            payload = store.load(session_dir)
            restored_options = store.restore_options(payload["options"])
            resumed = SimpleNamespace(dictionary=None)
            SessionStore(restored_options).apply_to_controller(resumed, payload)

        self.assertEqual(resumed.directories, ["current/", "next/"])
        self.assertEqual(resumed.jobs_processed, 3)
        self.assertEqual(restored_options["urls"], target_urls)

        self.assertEqual(
            [next(resumed.dictionary), next(resumed.dictionary)],
            ["in-flight", "later"],
        )
        with self.assertRaises(StopIteration):
            next(resumed.dictionary)

        for boundary in ("next job", "next target"):
            with self.subTest(boundary=boundary):
                resumed.dictionary.reset()
                self.assertEqual(
                    [
                        next(resumed.dictionary),
                        next(resumed.dictionary),
                        next(resumed.dictionary),
                    ],
                    ["done", "in-flight", "later"],
                )
                with self.assertRaises(StopIteration):
                    next(resumed.dictionary)

    @skipIf(os.name == "nt", "POSIX mode bits are unavailable on Windows")
    def test_new_session_directory_and_files_are_private(self):
        with tempfile.TemporaryDirectory() as root:
            for umask in (0o000, 0o022):
                with self.subTest(umask=oct(umask)):
                    session_dir = os.path.join(root, f"session-{umask:o}")
                    previous_umask = os.umask(umask)
                    try:
                        SessionStore({"auth": "alice:secret"}).save(
                            self._controller(), session_dir, ""
                        )
                    finally:
                        os.umask(previous_umask)

                    self.assertEqual(
                        stat.S_IMODE(os.stat(session_dir).st_mode),
                        0o700,
                    )
                    for file_name in SessionStore.FILES.values():
                        with self.subTest(file_name=file_name):
                            file_path = os.path.join(session_dir, file_name)
                            self.assertEqual(
                                stat.S_IMODE(os.stat(file_path).st_mode),
                                0o600,
                            )

    @skipIf(os.name == "nt", "POSIX mode bits are unavailable on Windows")
    def test_resaving_legacy_session_tightens_file_permissions(self):
        with tempfile.TemporaryDirectory() as root:
            session_dir = os.path.join(root, "session")
            store = SessionStore({"auth": "alice:secret"})
            store.save(self._controller(), session_dir, "")
            os.chmod(session_dir, 0o755)
            for file_name in SessionStore.FILES.values():
                os.chmod(os.path.join(session_dir, file_name), 0o644)

            store.save(self._controller(), session_dir, "")

            self.assertEqual(
                stat.S_IMODE(os.stat(session_dir).st_mode),
                0o755,
            )
            for file_name in SessionStore.FILES.values():
                with self.subTest(file_name=file_name):
                    file_path = os.path.join(session_dir, file_name)
                    self.assertEqual(
                        stat.S_IMODE(os.stat(file_path).st_mode),
                        0o600,
                    )

    def test_bytes_marker_in_headers_remains_a_header_mapping(self):
        marker = SessionStore.SESSION_BYTES_MARKER
        headers = {marker: "header-value"}

        restored = SessionStore({}).restore_options({"headers": headers})

        self.assertEqual(restored["headers"], headers)

    def test_invalid_request_body_encoding_is_rejected(self):
        serialized = {
            "data": {SessionStore.SESSION_BYTES_MARKER: "not base64!"}
        }

        with self.assertRaisesRegex(
            UnpicklingError,
            "Invalid binary session option: data",
        ):
            SessionStore({}).restore_options(serialized)
