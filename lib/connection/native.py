from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from lib.connection.response import NativeResponse
from lib.core.data import options
from lib.core.exceptions import RequestException
from lib.core.native_runtime import get_native_backend_install_error
from lib.core.settings import MAX_RESPONSE_SIZE
from lib.parse.url import append_query_string
from lib.utils.common import safequote


class NativeHTTPBackend:
    def __init__(self) -> None:
        try:
            import dirsearch_native
        except ImportError as e:
            raise RequestException(get_native_backend_install_error()) from e

        self._native = dirsearch_native

    def scan(
        self,
        base_url: str,
        paths: Iterable[str],
        query: str = "",
        *,
        apply_filters: bool = True,
    ) -> Iterator[tuple[str, NativeResponse | None, RequestException | None]]:
        raw_paths = list(paths)
        request_paths = [append_query_string(path, query) for path in raw_paths]
        quoted_paths = [safequote(path) for path in request_paths]
        filter_options = (
            self._filter_options() if apply_filters else self._disabled_filter_options()
        )
        results = self._native.scan_http(
            base_url,
            quoted_paths,
            concurrency=options["thread_count"],
            timeout_secs=options["timeout"],
            headers=list(options["headers"].items()),
            max_retries=options["max_retries"],
            delay_secs=options["delay"],
            follow_redirects=options["follow_redirects"],
            max_body_size=MAX_RESPONSE_SIZE,
            **filter_options,
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
                    length=getattr(result, "length", None),
                    filtered=getattr(result, "filtered", False),
                    filter_reason=getattr(result, "filter_reason", None),
                ),
                None,
            )

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
            "match_time": list(options["match_time"]),
            "filter_time": list(options["filter_time"]),
        }

    @staticmethod
    def _disabled_filter_options() -> dict[str, Any]:
        return {
            "include_status_codes": [],
            "exclude_status_codes": [],
            "minimum_response_size": 0,
            "maximum_response_size": 0,
            "matcher_mode": "or",
            "filter_mode": "or",
            "match_status_codes": [],
            "filter_status_codes": [],
            "match_sizes": [],
            "filter_sizes": [],
            "match_words": [],
            "filter_words": [],
            "match_lines": [],
            "filter_lines": [],
            "match_regex": None,
            "filter_regex": None,
            "match_time": [],
            "filter_time": [],
        }
