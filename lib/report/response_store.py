# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass

from lib.connection.response import BaseResponse
from lib.utils.file import FileUtils


@dataclass(frozen=True)
class ResponseArtifact:
    """Backend-neutral response data passed to response stores."""

    timestamp: str
    url: str
    status: int
    headers: tuple[tuple[str, str], ...]
    content_length: int
    content_type: str
    redirect: str
    elapsed: float
    body: bytes
    body_complete: bool
    body_truncated: bool

    @classmethod
    def from_response(cls, response: BaseResponse) -> ResponseArtifact:
        return cls(
            timestamp=response.datetime,
            url=response.url,
            status=response.status,
            headers=tuple(
                (str(name), str(value)) for name, value in response.headers.items()
            ),
            content_length=response.length,
            content_type=response.type,
            redirect=response.redirect,
            elapsed=response.elapsed,
            body=bytes(response.body),
            body_complete=response.body_complete,
            body_truncated=response.body_truncated,
        )


class _SaveOperationState(threading.local):
    """Per-thread nesting state for tracked response-store writes."""

    def __init__(self) -> None:
        self.depth = 0


class BaseResponseStore(ABC):
    """Shared lifecycle and async adapter for response artifact stores."""

    name = "response"

    def __init__(self, destination: str) -> None:
        self.destination = FileUtils.get_abs_path(destination)
        self._lifecycle = threading.Condition()
        self._save_local = _SaveOperationState()
        self._active_saves = 0
        self._closing = False
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lifecycle:
            return self._closed

    def ensure_open(self) -> None:
        with self._lifecycle:
            if self._closing or self._closed:
                raise OSError(f"Response store is closed: {self.destination}")

    @contextmanager
    def save_operation(self) -> Iterator[None]:
        """Register one save so close rejects new work and drains this one."""
        depth = self._save_local.depth
        if depth:
            self._save_local.depth = depth + 1
            try:
                yield
            finally:
                self._save_local.depth -= 1
            return

        with self._lifecycle:
            if self._closing or self._closed:
                raise OSError(f"Response store is closed: {self.destination}")
            self._active_saves += 1
            self._save_local.depth = 1

        try:
            yield
        finally:
            self._save_local.depth = 0
            with self._lifecycle:
                self._active_saves -= 1
                if self._active_saves == 0:
                    self._lifecycle.notify_all()

    @abstractmethod
    def save(self, artifact: ResponseArtifact) -> str:
        raise NotImplementedError

    async def save_async(self, artifact: ResponseArtifact) -> str:
        """Offload and drain synchronous saves before propagating cancellation."""
        task = asyncio.create_task(asyncio.to_thread(self._save_tracked, artifact))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # asyncio cannot stop a thread that is already running. Wait for
            # the owned write so controller teardown cannot close the store
            # and then observe that thread commit a late artifact.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            with suppress(Exception):
                task.result()
            raise

    def _save_tracked(self, artifact: ResponseArtifact) -> str:
        # The outer guard also covers third-party synchronous implementations
        # that rely on BaseResponseStore.save_async(). Built-in stores guard
        # direct save() calls as well; nesting is thread-local and counted once.
        with self.save_operation():
            return self.save(artifact)

    def _close_resources(self) -> None:
        """Close store-specific resources after all accepted saves drain."""

    def close(self) -> None:
        if self._save_local.depth:
            raise RuntimeError("Cannot close a response store from an active save")

        with self._lifecycle:
            if self._closed:
                return
            if self._closing:
                self._lifecycle.wait_for(lambda: self._closed)
                return
            self._closing = True
            self._lifecycle.wait_for(lambda: self._active_saves == 0)

        try:
            self._close_resources()
        finally:
            with self._lifecycle:
                self._closed = True
                self._closing = False
                self._lifecycle.notify_all()

    def __enter__(self) -> BaseResponseStore:
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def create_response_stores(
    directory: str | None,
    jsonl_file: str | None,
) -> tuple[BaseResponseStore, ...]:
    """Build configured stores while keeping controller orchestration generic."""
    from .directory_response_store import DirectoryResponseStore
    from .jsonl_response_store import JsonlResponseStore

    stores: list[BaseResponseStore] = []
    try:
        if directory:
            stores.append(DirectoryResponseStore(directory))
        if jsonl_file:
            stores.append(JsonlResponseStore(jsonl_file))
    except Exception:
        for store in stores:
            store.close()
        raise
    return tuple(stores)
