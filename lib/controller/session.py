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

import base64
import binascii
from collections.abc import Iterable
import json
import os
from typing import Any

from lib.core.dictionary import Dictionary
from lib.core.exceptions import InvalidURLException, UnpicklingError
from lib.core.logger import logger
from lib.core.report_config import ReportConfig
from lib.core.wordlist_config import WordlistConfig
from lib.report.manager import ReportManager
from lib.utils.file import FileUtils
from lib.view.terminal import interface


class SessionStore:
    SESSION_VERSION = 1
    SESSION_BYTES_MARKER = "__dirsearch_bytes_b64__"
    CHECKPOINT_FILE = "dirsearch-session.json"
    SESSION_OPTION_SET_KEYS = {
        "recursion_status_codes",
        "include_status_codes",
        "exclude_status_codes",
        "exclude_sizes",
        "skip_on_status",
        "match_status_codes",
        "filter_status_codes",
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
        self.invalid_sessions: list[tuple[str, str]] = []

    def list_sessions(self, base_path: str) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        self.invalid_sessions = []

        if os.path.isfile(base_path):
            summary = self._summarize_session_file(base_path)
            if summary:
                sessions.append(summary)
            return sessions

        if not os.path.isdir(base_path):
            return sessions

        for root, dirs, files in os.walk(base_path):
            is_session_dir = (
                self.CHECKPOINT_FILE in files
                or self.FILES["meta"] in files
            )
            if root == base_path:
                for file_name in files:
                    if is_session_dir and file_name == self.CHECKPOINT_FILE:
                        continue
                    summary = self._summarize_session_file(
                        FileUtils.build_path(root, file_name)
                    )
                    if summary:
                        sessions.append(summary)

            if is_session_dir:
                summary = self._summarize_session_dir(root)
                if summary:
                    sessions.append(summary)
                dirs.clear()

        sessions.sort(key=lambda item: item["path"])
        return sessions

    def load(self, session_path: str) -> dict[str, Any]:
        session_dir, checkpoint_path, _ = self._resolve_session_paths(
            session_path
        )
        if os.path.isfile(checkpoint_path):
            payload = self._read_json(checkpoint_path)
            self._validate_payload(payload)
            return payload

        meta_payload = self._read_json(
            FileUtils.build_path(session_dir, self.FILES["meta"])
        )
        payload = {
            "version": meta_payload["version"],
            "last_output": meta_payload.get("last_output", ""),
            "output_history": meta_payload.get("output_history", []),
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
        session_dir, checkpoint_path, uses_session_directory = (
            self._resolve_session_paths(session_path)
        )
        output_history = self._get_controller_history(controller)
        if output_history is None:
            output_history = self._load_output_history(session_path)
        else:
            output_history = list(output_history)
        if last_output:
            output_history.append(
                {"start_time": controller.start_time, "output": last_output}
            )
        payload = {
            "version": self.SESSION_VERSION,
            "controller": self._serialize_controller_state(controller),
            "dictionary": self._serialize_dictionary(controller),
            "options": self._serialize_options(),
            "last_output": last_output,
            "output_history": output_history,
        }
        if uses_session_directory:
            FileUtils.create_private_dir(session_dir)
        self._write_json(checkpoint_path, payload)
        if uses_session_directory:
            self._delete_session_files(session_dir, self.FILES.values())
        controller.output_history = output_history

    def delete(self, session_path: str) -> None:
        """Delete session-owned files without removing unrelated entries."""
        if os.path.islink(session_path) or not os.path.isdir(session_path):
            os.remove(session_path)
            return

        self._delete_session_files(
            session_path,
            (*self.FILES.values(), self.CHECKPOINT_FILE),
        )

        if not os.listdir(session_path):
            os.rmdir(session_path)

    def apply_to_controller(
        self,
        controller: Any,
        payload: dict[str, Any],
        *,
        wordlist_config: WordlistConfig,
    ) -> None:
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
        controller.dictionary = Dictionary(wordlist_config)
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
            controller.reporter = ReportManager(ReportConfig.from_options(self.options))
        except InvalidURLException as error:
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
            elif (
                key == "data"
                and isinstance(value, dict)
                and set(value) == {self.SESSION_BYTES_MARKER}
            ):
                try:
                    restored[key] = base64.b64decode(
                        value[self.SESSION_BYTES_MARKER],
                        validate=True,
                    )
                except (binascii.Error, TypeError, ValueError) as error:
                    raise UnpicklingError(
                        f"Invalid binary session option: {key}"
                    ) from error
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
            if key == "data" and isinstance(value, bytes):
                serialized[key] = {
                    self.SESSION_BYTES_MARKER: base64.b64encode(value).decode("ascii")
                }
            elif isinstance(value, (set, tuple)):
                serialized[key] = list(value)
            else:
                serialized[key] = value
        return serialized

    def _resolve_session_paths(
        self,
        session_path: str,
    ) -> tuple[str, str, bool]:
        """Resolve an existing checkpoint file or a session directory."""
        if os.path.isfile(session_path):
            return FileUtils.parent(session_path), session_path, False

        return (
            session_path,
            FileUtils.build_path(session_path, self.CHECKPOINT_FILE),
            True,
        )

    def _delete_session_files(
        self,
        session_dir: str,
        file_names: Iterable[str],
    ) -> None:
        for file_name in file_names:
            try:
                FileUtils.remove(FileUtils.build_path(session_dir, file_name))
            except FileNotFoundError:
                pass

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
        ) as error:
            raise UnpicklingError(str(error)) from error
        if not isinstance(payload, dict):
            raise UnpicklingError("Session JSON root must be an object")
        return payload

    def _write_json(self, path: str, payload: dict[str, Any]) -> None:
        with FileUtils.atomic_write_private_text(path) as file_handle:
            json.dump(payload, file_handle, indent=2, ensure_ascii=False)

    def _validate_payload(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise UnpicklingError("Session payload must be an object")
        if payload.get("version") != self.SESSION_VERSION:
            raise UnpicklingError("Unsupported session format version")
        for key in ("controller", "dictionary", "options"):
            if not isinstance(payload.get(key), dict):
                raise UnpicklingError(f"Invalid {key} session data")

        self._validate_controller_state(payload["controller"])
        self._validate_dictionary_state(payload["dictionary"])
        self._validate_options_state(payload["options"])

        last_output = payload.get("last_output")
        if last_output is not None and not isinstance(last_output, str):
            raise UnpicklingError("Invalid last_output session data")
        output_history = payload.get("output_history")
        if output_history is not None:
            if not isinstance(output_history, list) or any(
                not isinstance(entry, dict)
                or not isinstance(entry.get("output"), str)
                for entry in output_history
            ):
                raise UnpicklingError("Invalid output_history session data")

    @staticmethod
    def _validate_controller_state(controller: dict[str, Any]) -> None:
        for key in ("url", "base_path"):
            value = controller.get(key)
            if value is not None and not isinstance(value, str):
                raise UnpicklingError(f"Invalid controller.{key} session data")

        for key in ("directories", "passed_urls"):
            value = controller.get(key)
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
            ):
                raise UnpicklingError(f"Invalid controller.{key} session data")

        for key in ("jobs_processed", "errors", "consecutive_errors"):
            value = controller.get(key)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise UnpicklingError(f"Invalid controller.{key} session data")

        start_time = controller.get("start_time")
        if start_time is not None and (
            not isinstance(start_time, (int, float))
            or isinstance(start_time, bool)
        ):
            raise UnpicklingError("Invalid controller.start_time session data")

        old_session = controller.get("old_session")
        if old_session is not None and not isinstance(old_session, bool):
            raise UnpicklingError("Invalid controller.old_session session data")

    @staticmethod
    def _validate_dictionary_state(dictionary: dict[str, Any]) -> None:
        items = dictionary.get("items")
        index = dictionary.get("index")
        extra = dictionary.get("extra", [])
        extra_index = dictionary.get("extra_index", 0)

        if not isinstance(items, list) or any(
            not isinstance(item, str) for item in items
        ):
            raise UnpicklingError("Invalid dictionary.items session data")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index <= len(items)
        ):
            raise UnpicklingError("Invalid dictionary.index session data")
        if not isinstance(extra, list) or any(
            not isinstance(item, str) for item in extra
        ):
            raise UnpicklingError("Invalid dictionary.extra session data")
        if (
            not isinstance(extra_index, int)
            or isinstance(extra_index, bool)
            or not 0 <= extra_index <= len(extra)
        ):
            raise UnpicklingError("Invalid dictionary.extra_index session data")

    @staticmethod
    def _validate_options_state(session_options: dict[str, Any]) -> None:
        urls = session_options.get("urls")
        if urls is not None and (
            not isinstance(urls, list)
            or any(not isinstance(url, str) for url in urls)
        ):
            raise UnpicklingError("Invalid options.urls session data")

        output_formats = session_options.get("output_formats")
        if output_formats is not None and (
            not isinstance(output_formats, list)
            or any(not isinstance(item, str) for item in output_formats)
        ):
            raise UnpicklingError("Invalid options.output_formats session data")

    def _get_controller_history(self, controller: Any) -> list[dict[str, Any]] | None:
        if not hasattr(controller, "output_history"):
            return None
        history = controller.output_history
        if isinstance(history, list):
            return history
        return None

    def _load_output_history(self, session_path: str) -> list[dict[str, Any]]:
        session_dir, checkpoint_path, _ = self._resolve_session_paths(
            session_path
        )
        if os.path.isfile(checkpoint_path):
            try:
                checkpoint_payload = self._read_json(checkpoint_path)
            except UnpicklingError:
                return []
            if checkpoint_payload.get("version") != self.SESSION_VERSION:
                return []
            return self._deserialize_output_history(
                checkpoint_payload,
                checkpoint_payload.get("controller", {}).get("start_time"),
            )

        meta_path = FileUtils.build_path(session_dir, self.FILES["meta"])
        if not os.path.isfile(meta_path):
            return []
        try:
            meta_payload = self._read_json(meta_path)
        except UnpicklingError:
            return []
        if meta_payload.get("version") != self.SESSION_VERSION:
            return []
        start_time = None
        controller_path = FileUtils.build_path(
            session_dir, self.FILES["controller"]
        )
        if os.path.isfile(controller_path):
            try:
                controller_payload = self._read_json(controller_path)
                start_time = controller_payload.get("start_time")
            except UnpicklingError:
                start_time = None
        return self._deserialize_output_history(meta_payload, start_time)

    def _deserialize_output_history(
        self,
        payload: dict[str, Any],
        start_time: Any,
    ) -> list[dict[str, Any]]:
        history_payload = payload.get("output_history")
        if isinstance(history_payload, list):
            history: list[dict[str, Any]] = []
            for entry in history_payload:
                if not isinstance(entry, dict):
                    continue
                output = entry.get("output")
                if output is None:
                    continue
                history.append(
                    {"start_time": entry.get("start_time"), "output": output}
                )
            return history

        last_output = payload.get("last_output")
        if not last_output:
            return []

        return [{"start_time": start_time, "output": last_output}]

    def _summarize_session_dir(self, session_dir: str) -> dict[str, Any] | None:
        checkpoint_path = FileUtils.build_path(
            session_dir, self.CHECKPOINT_FILE
        )
        if os.path.isfile(checkpoint_path):
            try:
                payload = self._read_json(checkpoint_path)
                self._validate_payload(payload)
            except UnpicklingError as error:
                self._record_invalid_session(session_dir, error)
                return None
            return self._build_summary(
                session_dir,
                checkpoint_path,
                payload["controller"],
                payload["options"],
            )

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
        except UnpicklingError as error:
            self._record_invalid_session(session_dir, error)
            return None
        try:
            self._validate_controller_state(controller_payload)
            self._validate_options_state(options_payload)
            return self._build_summary(
                session_dir, meta_path, controller_payload, options_payload
            )
        except UnpicklingError as error:
            self._record_invalid_session(session_dir, error)
            return None

    def _summarize_session_file(self, session_file: str) -> dict[str, Any] | None:
        try:
            payload = self._read_json(session_file)
        except UnpicklingError:
            return None
        if payload.get("version") != self.SESSION_VERSION:
            return None
        try:
            self._validate_payload(payload)
            return self._build_summary(
                session_file,
                session_file,
                payload["controller"],
                payload["options"],
            )
        except UnpicklingError as error:
            self._record_invalid_session(session_file, error)
            return None

    def _record_invalid_session(
        self,
        session_path: str,
        error: UnpicklingError,
    ) -> None:
        self.invalid_sessions.append((session_path, str(error)))

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
