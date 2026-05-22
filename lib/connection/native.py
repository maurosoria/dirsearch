from __future__ import annotations

from collections.abc import Iterable, Iterator

from lib.connection.response import NativeResponse
from lib.core.data import options
from lib.core.exceptions import RequestException
from lib.core.settings import MAX_RESPONSE_SIZE
from lib.utils.common import safequote


class NativeHTTPBackend:
    def __init__(self) -> None:
        try:
            import dirsearch_native
        except ImportError as e:
            raise RequestException(
                "Native request backend is not available. "
                "Build it with: python3 -m maturin develop --manifest-path native/Cargo.toml"
            ) from e

        self._native = dirsearch_native

    def scan(
        self,
        base_url: str,
        paths: Iterable[str],
    ) -> Iterator[tuple[str, NativeResponse | None, RequestException | None]]:
        raw_paths = list(paths)
        quoted_paths = [safequote(path) for path in raw_paths]
        results = self._native.scan_http(
            base_url,
            quoted_paths,
            concurrency=options["thread_count"],
            timeout_secs=options["timeout"],
            headers=list(options["headers"].items()),
            max_retries=options["max_retries"],
            follow_redirects=options["follow_redirects"],
            max_body_size=MAX_RESPONSE_SIZE,
        )

        for path, quoted_path, result in zip(raw_paths, quoted_paths, results):
            if result.error is not None:
                yield path, None, RequestException(result.error)
                continue

            yield (
                path,
                NativeResponse(
                    base_url + quoted_path,
                    result.status,
                    result.headers,
                    result.body,
                    result.elapsed_ms / 1000,
                ),
                None,
            )
