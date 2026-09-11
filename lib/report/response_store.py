# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
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


class BaseResponseStore(ABC):
    """Shared lifecycle and async adapter for response artifact stores."""

    name = "response"

    def __init__(self, destination: str) -> None:
        self.destination = FileUtils.get_abs_path(destination)
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def ensure_open(self) -> None:
        if self.closed:
            raise OSError(f"Response store is closed: {self.destination}")

    @abstractmethod
    def save(self, artifact: ResponseArtifact) -> str:
        raise NotImplementedError

    async def save_async(self, artifact: ResponseArtifact) -> str:
        """Offload synchronous stores; native async stores may override this."""
        return await asyncio.to_thread(self.save, artifact)

    def close(self) -> None:
        self._closed = True

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
