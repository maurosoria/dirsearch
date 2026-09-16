from __future__ import annotations

import threading

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from lib.connection.proxy import (
    PROXY_AUTHENTICATION_REQUIRED,
    add_proxy_authentication,
    format_proxy_error,
    is_proxy_connect_rejection,
    proxy_error_status,
)
from lib.connection.response import NativeResponse
from lib.core.data import options
from lib.core.exceptions import RequestException
from lib.core.native_runtime import (
    get_native_backend_install_error,
    get_native_extension_version_error,
)
from lib.core.settings import MAX_RESPONSE_SIZE
from lib.parse.url import append_query_string
from lib.utils.common import safequote


def _quote_native_path(path: str) -> str:
    """Skip urllib's byte round-trip for already URL-safe ASCII paths."""

    if path.isascii() and path.isprintable() and " " not in path:
        return path
    return safequote(path)


@dataclass(frozen=True, slots=True)
class NativeScanEvent:
    """One actionable Rust result, indexed into the original path batch."""

    request_index: int
    path: str
    response: NativeResponse | None
    error: RequestException | None


@dataclass(frozen=True, slots=True)
class NativeScanBatch:
    """Compact results plus the number of paths Rust finished processing."""

    processed_count: int
    events: tuple[NativeScanEvent, ...]


class NativeHTTPBackend:
    def __init__(self, proxy_override: str | None = None) -> None:
        try:
            import dirsearch_native
        except ImportError as e:
            raise RequestException(get_native_backend_install_error()) from e

        if version_error := get_native_extension_version_error(dirsearch_native):
            raise RequestException(version_error)

        self._native = dirsearch_native
        self._engine = None
        self._engine_config = None
        self._proxy_override = proxy_override
        self._cancel_lock = threading.Lock()
        # Preserve cancellation requested before lazy engine creation.
        self._cancel_generation = 0
        self._consumed_cancel_generation = 0

    def _get_engine(self):
        proxies = (
            self._normalize_proxy_urls([self._proxy_override])
            if self._proxy_override is not None
            else self._proxy_urls()
        )
        config = {
            "concurrency": options["thread_count"],
            "timeout_secs": options["timeout"],
            "headers": list(options["headers"].items()),
            "proxies": proxies,
            "follow_redirects": options["follow_redirects"],
        }
        if self._engine is None or config != self._engine_config:
            self._engine = self._native.NativeHttpEngine(**config)
            self._engine_config = config
        return self._engine

    def cancel(self) -> None:
        with self._cancel_lock:
            self._cancel_generation += 1
            if self._engine is not None:
                self._engine.cancel()

    def reset_cancel(self) -> None:
        with self._cancel_lock:
            self._consumed_cancel_generation = self._cancel_generation
            if self._engine is not None:
                self._engine.reset_cancel()

    def scan(
        self,
        base_url: str,
        paths: Iterable[str],
        query: str = "",
    ) -> Iterator[tuple[str, NativeResponse | None, RequestException | None]]:
        raw_paths, quoted_paths, results = self._scan(
            base_url, paths, query, compact_filtered=False
        )

        for path, quoted_path, result in zip(raw_paths, quoted_paths, results):
            response, error = self._convert_result(base_url, quoted_path, result)
            yield path, response, error

    def scan_batch(
        self,
        base_url: str,
        paths: list[str],
        query: str = "",
    ) -> NativeScanBatch:
        """Scan NativeFuzzer's owned list without copying its references."""

        raw_paths, quoted_paths, results = self._scan(
            base_url,
            paths,
            query,
            compact_filtered=True,
            reuse_paths=True,
        )
        if not results:
            return NativeScanBatch(0, ())

        # Rust retains the last processed result as a completion marker. Its
        # index lets Python account for trailing filtered misses without
        # receiving one PyO3 object for every miss.
        processed_count = results[-1].request_index + 1
        events = []
        for result in results:
            # Interior filtered results are represented by gaps between event
            # indexes. Proxy authentication remains actionable as an error.
            if result.filtered and not (
                self._using_proxy
                and result.status == PROXY_AUTHENTICATION_REQUIRED
            ):
                continue
            request_index = result.request_index
            response, error = self._convert_result(
                base_url, quoted_paths[request_index], result
            )
            events.append(
                NativeScanEvent(
                    request_index,
                    raw_paths[request_index],
                    response,
                    error,
                )
            )

        return NativeScanBatch(processed_count, tuple(events))

    def scan_unfiltered(
        self,
        base_url: str,
        path: str,
        query: str = "",
    ) -> tuple[NativeResponse | None, RequestException | None]:
        _raw_paths, quoted_paths, results = self._scan(
            base_url,
            [path],
            query,
            compact_filtered=False,
            apply_filters=False,
        )
        if not results:
            return None, RequestException("Native request was cancelled")
        return self._convert_result(base_url, quoted_paths[0], results[0])

    def _scan(
        self,
        base_url: str,
        paths: Iterable[str],
        query: str,
        *,
        compact_filtered: bool,
        apply_filters: bool = True,
        reuse_paths: bool = False,
    ) -> tuple[list[str], list[str], list[Any]]:
        # NativeFuzzer already owns a stable list for the duration of this
        # synchronous call. Reuse it instead of copying every batch boundary.
        raw_paths = paths if reuse_paths and isinstance(paths, list) else list(paths)
        quoted_paths = [
            _quote_native_path(append_query_string(path, query))
            for path in raw_paths
        ]
        with self._cancel_lock:
            engine = self._get_engine()
            cancel_generation = self._cancel_generation
            if cancel_generation != self._consumed_cancel_generation:
                engine.cancel()

        results = engine.scan(
            base_url,
            quoted_paths,
            max_retries=options["max_retries"],
            max_body_size=MAX_RESPONSE_SIZE,
            compact_filtered=compact_filtered,
            **(self._filter_options() if apply_filters else {}),
        )
        with self._cancel_lock:
            self._consumed_cancel_generation = self._cancel_generation

        return raw_paths, quoted_paths, results

    def _convert_result(
        self,
        base_url: str,
        quoted_path: str,
        result: Any,
    ) -> tuple[NativeResponse | None, RequestException | None]:
        if result.error is not None:
            error_message = result.error
            if (
                self._using_proxy
                and (
                    proxy_error_status(error_message) is not None
                    or is_proxy_connect_rejection(error_message)
                )
            ):
                error_message = format_proxy_error(error_message)
            return None, RequestException(error_message)

        if self._using_proxy and result.status == PROXY_AUTHENTICATION_REQUIRED:
            return None, RequestException("Proxy authentication required")

        return (
            NativeResponse(
                base_url + quoted_path,
                result.status,
                result.headers,
                result.body,
                result.elapsed_ms / 1000,
                length=result.length,
                filtered=result.filtered,
                filter_reason=result.filter_reason,
                body_complete=result.body_complete,
            ),
            None,
        )

    @staticmethod
    def _proxy_urls() -> list[str]:
        return NativeHTTPBackend._normalize_proxy_urls(options["proxies"])

    @staticmethod
    def _normalize_proxy_urls(proxy_values: Iterable[str]) -> list[str]:
        proxies = []
        for proxy in proxy_values:
            if "://" not in proxy:
                proxy = f"http://{proxy}"
            elif not proxy.startswith(("http://", "https://")):
                raise RequestException(
                    "--request-backend native supports HTTP and HTTPS proxies only"
                )

            proxy = add_proxy_authentication(proxy, options["proxy_auth"])
            proxies.append(proxy)

        return proxies

    @property
    def _using_proxy(self) -> bool:
        return self._proxy_override is not None or bool(options["proxies"])

    @staticmethod
    def _filter_options() -> dict[str, Any]:
        return {
            "include_status_codes": sorted(options["include_status_codes"]),
            "exclude_status_codes": sorted(options["exclude_status_codes"]),
            "minimum_response_size": options["minimum_response_size"],
            "maximum_response_size": options["maximum_response_size"],
            "matcher_mode": options["matcher_mode"],
            "filter_mode": options["filter_mode"],
            "match_status_codes": sorted(options["match_status_codes"]),
            "filter_status_codes": sorted(options["filter_status_codes"]),
            "match_sizes": list(options["match_sizes"]),
            "filter_sizes": list(options["filter_sizes"]),
            "match_words": list(options["match_words"]),
            "filter_words": list(options["filter_words"]),
            "match_lines": list(options["match_lines"]),
            "filter_lines": list(options["filter_lines"]),
            "match_regex": options["match_regex"],
            "filter_regex": options["filter_regex"],
            "match_headers": list(options["match_headers"]),
            "filter_headers": list(options["filter_headers"]),
            "match_header_regex": options["match_header_regex"],
            "filter_header_regex": options["filter_header_regex"],
            "match_time": list(options["match_time"]),
            "filter_time": list(options["filter_time"]),
        }


class NativeRequester:
    """Minimal requester facade used by native scans and calibration."""

    def __init__(self) -> None:
        self._url = ""
        self._query = ""
        # Controller creates the requester before entering its per-target error
        # handler. Delay the optional extension import until a scan actually
        # starts so a missing build is reported as a normal request error.
        self.backend: NativeHTTPBackend | None = None

    def get_backend(self) -> NativeHTTPBackend:
        if self.backend is None:
            self.backend = NativeHTTPBackend()
        return self.backend

    @property
    def rate(self) -> int:
        return 0

    def set_url(self, url: str) -> None:
        self._url = url

    def set_query(self, query: str) -> None:
        self._query = query

    def set_ip(self, *_args) -> None:
        raise RequestException("--request-backend native does not support --ip yet")

    def reset_auth(self) -> None:
        return None

    def set_auth(self, *_args) -> None:
        raise RequestException(
            "--request-backend native does not support authentication yet"
        )

    def request(self, path: str, proxy: str | None = None) -> NativeResponse:
        backend = (
            NativeHTTPBackend(proxy_override=proxy)
            if proxy
            else self.get_backend()
        )
        response, error = backend.scan_unfiltered(self._url, path, self._query)
        if error is not None:
            raise error
        if response is None:
            raise RequestException("Native request returned no response")
        return response

    def close(self) -> None:
        return None
