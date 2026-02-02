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
from typing import Any

import mysql.connector
import psycopg

from lib.core.exceptions import InvalidURLException, UnpicklingError
from lib.core.logger import logger
from lib.report.manager import ReportManager
from lib.utils.file import FileUtils
from lib.view.terminal import interface


class SessionStore:
    SESSION_VERSION = 1
    SESSION_OPTION_SET_KEYS = {
        "recursion_status_codes",
        "include_status_codes",
        "exclude_status_codes",
        "exclude_sizes",
        "skip_on_status",
    }
    SESSION_OPTION_TUPLE_KEYS = {
        "extensions",
        "exclude_extensions",
        "prefixes",
        "suffixes",
    }
    FILES = {
        "meta": "meta.json",
        "controller": "controller.json",
        "dictionary": "dictionary.json",
        "options": "options.json",
    }

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options

    def list_sessions(self, base_path: str) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []

        if os.path.isfile(base_path):
            summary = self._summarize_session_file(base_path)
            if summary:
                sessions.append(summary)
            return sessions

        if not os.path.isdir(base_path):
            return sessions

        with os.scandir(base_path) as entries:
            for entry in entries:
                summary = None
                if entry.is_dir():
                    summary = self._summarize_session_dir(entry.path)
                elif entry.is_file():
                    summary = self._summarize_session_file(entry.path)
                if summary:
                    sessions.append(summary)

        sessions.sort(key=lambda item: item["path"])
        return sessions

    def load(self, session_path: str) -> dict[str, Any]:
        if os.path.isfile(session_path):
            payload = self._read_json(session_path)
            self._validate_payload(payload)
            return payload

        session_dir = self._get_session_dir(session_path)
        meta_payload = self._read_json(
            FileUtils.build_path(session_dir, self.FILES["meta"])
        )
        payload = {
            "version": meta_payload["version"],
            "last_output": meta_payload.get("last_output", ""),
            "controller": self._read_json(
                FileUtils.build_path(session_dir, self.FILES["controller"])
            ),
            "dictionary": self._read_json(
                FileUtils.build_path(session_dir, self.FILES["dictionary"])
            ),
            "options": self._read_json(
                FileUtils.build_path(session_dir, self.FILES["options"])
            ),
        }
        self._validate_payload(payload)
        return payload

    def save(self, controller: Any, session_path: str, last_output: str) -> None:
        payload = {
            "version": self.SESSION_VERSION,
            "controller": self._serialize_controller_state(controller),
            "dictionary": self._serialize_dictionary(controller),
            "options": self._serialize_options(),
            "last_output": last_output,
        }
        session_dir = self._get_session_dir(session_path)
        FileUtils.create_dir(session_dir)

        meta_path = FileUtils.build_path(session_dir, self.FILES["meta"])
        self._write_json(meta_path, {"version": payload["version"], "last_output": last_output})
        self._write_json(
            FileUtils.build_path(session_dir, self.FILES["controller"]),
            payload["controller"],
        )
        self._write_json(
            FileUtils.build_path(session_dir, self.FILES["dictionary"]),
            payload["dictionary"],
        )
        self._write_json(
            FileUtils.build_path(session_dir, self.FILES["options"]),
            payload["options"],
        )

    def apply_to_controller(self, controller: Any, payload: dict[str, Any]) -> None:
        controller_state = payload["controller"]
        controller.start_time = controller_state["start_time"]
        controller.passed_urls = set(controller_state.get("passed_urls", []))
        controller.directories = controller_state.get("directories", [])
        controller.jobs_processed = controller_state.get("jobs_processed", 0)
        controller.errors = controller_state.get("errors", 0)
        controller.consecutive_errors = controller_state.get("consecutive_errors", 0)
        controller.base_path = controller_state.get("base_path", "")
        controller.url = controller_state.get("url", "")
        controller.old_session = controller_state.get("old_session", True)
        if not hasattr(controller, "dictionary") or controller.dictionary is None:
            from lib.core.dictionary import Dictionary

            controller.dictionary = Dictionary()
        else:
            controller.dictionary = controller.dictionary.__class__()
        dictionary_state = payload["dictionary"]
        controller.dictionary.__setstate__(
            (
                dictionary_state["items"],
                dictionary_state["index"],
                dictionary_state.get("extra", []),
                dictionary_state.get("extra_index", 0),
            )
        )
        try:
            controller.reporter = ReportManager(self.options["output_formats"])
        except (
            InvalidURLException,
            mysql.connector.Error,
            psycopg.Error,
        ) as error:
            logger.exception(error)
            interface.error(str(error))
            raise SystemExit(1)

    def restore_options(self, serialized: dict[str, Any]) -> dict[str, Any]:
        restored: dict[str, Any] = {}
        for key, value in serialized.items():
            if key in self.SESSION_OPTION_SET_KEYS and value is not None:
                restored[key] = set(value)
            elif key in self.SESSION_OPTION_TUPLE_KEYS and value is not None:
                restored[key] = tuple(value)
            else:
                restored[key] = value
        return restored

    def _serialize_controller_state(self, controller: Any) -> dict[str, Any]:
        return {
            "start_time": controller.start_time,
            "passed_urls": sorted(controller.passed_urls),
            "directories": list(controller.directories),
            "jobs_processed": controller.jobs_processed,
            "errors": controller.errors,
            "consecutive_errors": controller.consecutive_errors,
            "base_path": controller.base_path,
            "url": controller.url,
            "old_session": controller.old_session,
        }

    def _serialize_dictionary(self, controller: Any) -> dict[str, Any]:
        items, index, extra, extra_index = controller.dictionary.__getstate__()
        return {
            "items": items,
            "index": index,
            "extra": extra,
            "extra_index": extra_index,
        }

    def _serialize_options(self) -> dict[str, Any]:
        serialized: dict[str, Any] = {}
        for key, value in self.options.items():
            if isinstance(value, (set, tuple)):
                serialized[key] = list(value)
            else:
                serialized[key] = value
        return serialized

    def _get_session_dir(self, session_path: str) -> str:
        return session_path

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                return json.load(file_handle)
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
        ) as error:
            raise UnpicklingError(str(error)) from error

    def _write_json(self, path: str, payload: dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, ensure_ascii=False)

    def _validate_payload(self, payload: dict[str, Any]) -> None:
        if payload.get("version") != self.SESSION_VERSION:
            raise UnpicklingError("Unsupported session format version")
        for key in ("controller", "dictionary", "options"):
            if key not in payload:
                raise UnpicklingError("Missing required session data")

    def _summarize_session_dir(self, session_dir: str) -> dict[str, Any] | None:
        meta_path = FileUtils.build_path(session_dir, self.FILES["meta"])
        if not os.path.isfile(meta_path):
            return None
        try:
            meta_payload = self._read_json(meta_path)
            if meta_payload.get("version") != self.SESSION_VERSION:
                return None
            controller_payload = self._read_json(
                FileUtils.build_path(session_dir, self.FILES["controller"])
            )
            options_payload = self._read_json(
                FileUtils.build_path(session_dir, self.FILES["options"])
            )
        except UnpicklingError:
            return None
        return self._build_summary(
            session_dir, meta_path, controller_payload, options_payload
        )

    def _summarize_session_file(self, session_file: str) -> dict[str, Any] | None:
        try:
            payload = self._read_json(session_file)
        except UnpicklingError:
            return None
        if payload.get("version") != self.SESSION_VERSION:
            return None
        controller_payload = payload.get("controller")
        options_payload = payload.get("options")
        if controller_payload is None or options_payload is None:
            return None
        return self._build_summary(
            session_file, session_file, controller_payload, options_payload
        )

    def _build_summary(
        self,
        session_path: str,
        meta_path: str,
        controller_state: dict[str, Any],
        options_state: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "path": session_path,
            "url": controller_state.get("url", ""),
            "targets_left": len(options_state.get("urls") or []),
            "directories_left": len(controller_state.get("directories") or []),
            "jobs_processed": controller_state.get("jobs_processed", 0),
            "errors": controller_state.get("errors", 0),
            "modified": os.path.getmtime(meta_path),
        }
