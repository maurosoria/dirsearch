# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import os
from urllib.parse import urlparse

from lib.core.settings import MAX_RESPONSE_FILENAME_LENGTH
from .response_store import BaseResponseStore, ResponseArtifact
from lib.utils.common import get_valid_filename
from lib.utils.file import FileUtils


def _truncate_filename(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def response_filename(
    url: str,
    status: int,
    max_length: int = MAX_RESPONSE_FILENAME_LENGTH,
) -> str:
    """Build a portable filename without exposing the raw query string."""
    parsed = urlparse(url)
    host = parsed.hostname or "response"
    if parsed.port is not None:
        host = f"{host}_{parsed.port}"

    name = get_valid_filename(f"{host}{parsed.path}")
    if parsed.query:
        query_hash = hashlib.sha256(parsed.query.encode("utf-8")).hexdigest()[:12]
        name = f"{name}_query-{query_hash}"

    name = name.strip(" ._") or "response"
    suffix = f"_{status}"
    return f"{_truncate_filename(name, max_length - len(suffix))}{suffix}"


class DirectoryResponseStore(BaseResponseStore):
    """Save one raw response body per exclusively created file."""

    name = "directory"

    def __init__(self, directory: str) -> None:
        super().__init__(directory)
        FileUtils.create_writable_dir(self.destination)

    def save(self, artifact: ResponseArtifact) -> str:
        with self.save_operation():
            return self._save(artifact)

    def _save(self, artifact: ResponseArtifact) -> str:
        base_name = response_filename(artifact.url, artifact.status)
        file_path, descriptor = self._claim_file(base_name)
        completed = False

        try:
            with os.fdopen(descriptor, "wb") as file_handle:
                descriptor = -1
                file_handle.write(artifact.body)
            completed = True
            return file_path
        finally:
            if descriptor != -1:
                os.close(descriptor)
            if not completed:
                try:
                    FileUtils.remove(file_path)
                except OSError:
                    pass

    def _claim_file(self, base_name: str) -> tuple[str, int]:
        counter = 0

        while True:
            collision_suffix = "" if counter == 0 else f"_{counter}"
            candidate_name = (
                f"{_truncate_filename(base_name, MAX_RESPONSE_FILENAME_LENGTH - len(collision_suffix))}"
                f"{collision_suffix}"
            )
            file_path = FileUtils.build_path(self.destination, candidate_name)
            try:
                descriptor = FileUtils.open_exclusive(file_path)
            except FileExistsError:
                counter += 1
                continue
            return file_path, descriptor
