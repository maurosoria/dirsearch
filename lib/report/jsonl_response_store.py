# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import json
import os
import threading

from .response_store import BaseResponseStore, ResponseArtifact
from lib.utils.file import FileUtils


JSONL_RESPONSE_SCHEMA = "dirsearch.response.v1"
# A multiple of three keeps separately encoded chunks concatenable as Base64.
JSONL_BASE64_CHUNK_SIZE = 57 * 1024


class JsonlResponseStore(BaseResponseStore):
    """Append complete JSONL records under a lock owned by this output file."""

    name = "jsonl"

    def __init__(self, file_path: str) -> None:
        super().__init__(file_path)
        parent = FileUtils.parent(self.destination)
        if parent:
            FileUtils.create_dir(parent)
        if FileUtils.exists(self.destination) and not FileUtils.is_file(
            self.destination
        ):
            raise IsADirectoryError(f"Not a file: {self.destination}")

        descriptor = FileUtils.open_binary_append(self.destination)
        try:
            self._file = os.fdopen(descriptor, "a+b", buffering=0)
        except Exception:
            os.close(descriptor)
            raise

        try:
            self._validate_existing_file()
            self._needs_separator = self._existing_file_needs_separator()
        except Exception:
            self._file.close()
            raise
        self._lock = threading.Lock()

    def _validate_existing_file(self) -> None:
        self._file.seek(0)
        for line_number, line in enumerate(self._file, 1):
            if not line.strip():
                raise ValueError(
                    f"Invalid blank JSONL record at line {line_number}"
                )
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Invalid JSONL record at line {line_number}"
                ) from error
            if (
                not isinstance(record, dict)
                or record.get("schema") != JSONL_RESPONSE_SCHEMA
            ):
                raise ValueError(
                    f"Unsupported JSONL record at line {line_number}"
                )

    def _existing_file_needs_separator(self) -> bool:
        self._file.seek(0, os.SEEK_END)
        if self._file.tell() == 0:
            return False
        self._file.seek(-1, os.SEEK_END)
        return self._file.read(1) != b"\n"

    def save(self, artifact: ResponseArtifact) -> str:
        metadata = {
            "schema": JSONL_RESPONSE_SCHEMA,
            "timestamp": artifact.timestamp,
            "url": artifact.url,
            "status": artifact.status,
            "headers": dict(artifact.headers),
            "contentLength": artifact.content_length,
            "capturedBodyLength": len(artifact.body),
            "bodyComplete": artifact.body_complete,
            "bodyTruncated": artifact.body_truncated,
            "contentType": artifact.content_type,
            "redirect": artifact.redirect,
            "elapsed": round(artifact.elapsed, 3),
            "bodyEncoding": "base64",
        }
        metadata_json = json.dumps(
            metadata,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        # json.dumps() ends this dictionary with "}"; stream the body before it.
        # HTTP metadata can contain strings that Python represents with lone
        # surrogates (for example after decoding malformed header bytes).
        # Preserve those values as JSON Unicode escapes without forcing normal
        # Unicode metadata to ASCII.
        prefix = (
            metadata_json[:-1].encode("utf-8", errors="backslashreplace")
            + b',"body":"'
        )

        with self._lock:
            self.ensure_open()

            original_size = os.fstat(self._file.fileno()).st_size
            try:
                if self._needs_separator:
                    self._write_all(b"\n")
                self._write_all(prefix)
                for offset in range(0, len(artifact.body), JSONL_BASE64_CHUNK_SIZE):
                    chunk = artifact.body[offset:offset + JSONL_BASE64_CHUNK_SIZE]
                    self._write_all(base64.b64encode(chunk))
                self._write_all(b'"}\n')
                self._file.flush()
            except OSError:
                try:
                    os.ftruncate(self._file.fileno(), original_size)
                    self._file.flush()
                except OSError:
                    pass
                raise
            self._needs_separator = False
        return self.destination

    def _write_all(self, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            written = self._file.write(remaining)
            if not written:
                raise OSError(f"Short write to response store: {self.destination}")
            remaining = remaining[written:]

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            try:
                self._file.flush()
            finally:
                self._file.close()
                super().close()
