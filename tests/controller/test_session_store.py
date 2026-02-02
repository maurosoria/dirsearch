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
import tempfile
from unittest import TestCase

from lib.controller.session import SessionStore


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
