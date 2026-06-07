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

import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from lib.core.exceptions import WordlistLimitError
from lib.core.fingerprint import fingerprint_headers, merge_fingerprints
from lib.core.preflight import PreflightProfile, PreflightResult
from lib.core.settings import DEFAULT_HEADERS, SCRIPT_PATH
from lib.core.structures import OrderedSet
from lib.core.wordlist_template import expand_template_line, normalize_placeholders
from lib.parse.rawrequest import parse_raw_content
from lib.parse.url import append_query_string, ensure_trailing_path_slash
from lib.utils.common import safequote
from lib.utils.file import FileUtils


__all__ = [
    "DirsearchFuzzer",
    "FuzzerConfig",
    "FuzzerResult",
    "PreflightResult",
    "Wordlist",
    "WordlistLimitError",
    "WordlistState",
    "WordlistTemplate",
]


@dataclass(frozen=True)
class FuzzerResult:
    url: str
    path: str
    status: int
    length: int
    content_type: str
    redirect: str = ""
    elapsed: float = 0.0
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass(frozen=True)
class WordlistState:
    items: tuple[str, ...]
    index: int = 0


@dataclass(frozen=True)
class Wordlist:
    items: tuple[str, ...]

    def __init__(self, items: Iterable[str], *, max_entries: int | None = None) -> None:
        object.__setattr__(
            self,
            "items",
            tuple(self._dedupe(items, max_entries=max_entries)),
        )

    @classmethod
    def from_file(cls, path: str) -> Wordlist:
        return cls(FileUtils.get_lines(path))

    @classmethod
    def from_template(
        cls,
        template: WordlistTemplate,
        *,
        extensions: Iterable[str] = (),
        placeholders: Mapping[str, Iterable[str] | str] | None = None,
        max_entries: int | None = None,
    ) -> Wordlist:
        return cls(
            template.render(extensions=extensions, placeholders=placeholders),
            max_entries=max_entries,
        )

    @staticmethod
    def _dedupe(
        items: Iterable[str],
        *,
        max_entries: int | None = None,
    ) -> Iterator[str]:
        seen = OrderedSet()
        for item in items:
            path = item.strip().lstrip("/")
            if not path or path.startswith("#") or path in seen:
                continue
            seen.add(path)
            if max_entries is not None and len(seen) > max_entries:
                raise WordlistLimitError(
                    f"Generated wordlist exceeded max_entries ({max_entries})"
                )
            yield path

    def __iter__(self) -> Iterator[str]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def state(self, index: int = 0) -> WordlistState:
        return WordlistState(items=self.items, index=index)


@dataclass(frozen=True)
class WordlistTemplate:
    lines: tuple[str, ...]
    placeholders: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __init__(
        self,
        lines: Iterable[str],
        placeholders: Mapping[str, Iterable[str] | str] | None = None,
    ) -> None:
        object.__setattr__(self, "lines", tuple(lines))
        object.__setattr__(
            self,
            "placeholders",
            self._normalize_placeholders(placeholders or {}),
        )

    @classmethod
    def from_file(
        cls,
        path: str,
        placeholders: Mapping[str, Iterable[str] | str] | None = None,
    ) -> WordlistTemplate:
        return cls(FileUtils.get_lines(path), placeholders=placeholders)

    @classmethod
    def from_builtin(
        cls,
        name: str,
        placeholders: Mapping[str, Iterable[str] | str] | None = None,
    ) -> WordlistTemplate:
        filename = name.strip()
        if not filename:
            raise ValueError("Built-in template name is required")
        if not filename.endswith(".txt"):
            filename += ".txt"
        if os.path.basename(filename) != filename:
            raise ValueError(f"Invalid built-in template name: {name}")

        path = FileUtils.build_path(SCRIPT_PATH, "db", "templates", filename)
        if not FileUtils.can_read(path):
            raise ValueError(f"Unknown built-in template: {name}")
        return cls.from_file(path, placeholders=placeholders)

    @staticmethod
    def _normalize_placeholders(
        placeholders: Mapping[str, Iterable[str] | str]
    ) -> dict[str, tuple[str, ...]]:
        return normalize_placeholders(placeholders)

    def render(
        self,
        *,
        extensions: Iterable[str] = (),
        placeholders: Mapping[str, Iterable[str] | str] | None = None,
    ) -> Iterator[str]:
        values = {f"%{key}%": value for key, value in self.placeholders.items()}
        values.update(placeholders or {})
        for line in self.lines:
            yield from expand_template_line(
                line,
                extensions=extensions,
                placeholders=values,
            )


@dataclass(frozen=True)
class FuzzerConfig:
    url: str
    wordlist: Wordlist | WordlistTemplate | Iterable[str]
    extensions: tuple[str, ...] = ()
    headers: Mapping[str, str] = field(default_factory=dict)
    http_method: str = "GET"
    data: bytes | str | None = None
    timeout: float = 10.0
    follow_redirects: bool = False
    include_status_codes: frozenset[int] = field(default_factory=frozenset)
    exclude_status_codes: frozenset[int] = field(
        default_factory=lambda: frozenset({404})
    )
    verify_tls: bool = False
    user_agent: str | None = None
    result_predicate: Callable[[FuzzerResult], bool] | None = None
    session_factory: Callable[[], requests.Session] | None = None
    raise_on_error: bool = False
    preflight: bool = False

    @classmethod
    def from_raw_request(
        cls,
        *,
        wordlist: Wordlist | WordlistTemplate | Iterable[str],
        raw_request: str | bytes | None = None,
        raw_file: str | None = None,
        scheme: str = "http",
        extensions: Iterable[str] = (),
        timeout: float = 10.0,
        follow_redirects: bool = False,
        include_status_codes: Iterable[int] = frozenset(),
        exclude_status_codes: Iterable[int] = frozenset({404}),
        verify_tls: bool = False,
        user_agent: str | None = None,
        result_predicate: Callable[[FuzzerResult], bool] | None = None,
        session_factory: Callable[[], requests.Session] | None = None,
        raise_on_error: bool = False,
        preflight: bool = False,
    ) -> FuzzerConfig:
        if (raw_request is None) == (raw_file is None):
            raise ValueError("Provide exactly one of raw_request or raw_file")

        if raw_file is not None:
            raw_request = FileUtils.read_bytes(raw_file)

        request = parse_raw_content(raw_request, scheme=scheme)

        return cls(
            url=request.url,
            wordlist=wordlist,
            extensions=tuple(extensions),
            headers=request.headers,
            http_method=request.method,
            data=request.body,
            timeout=timeout,
            follow_redirects=follow_redirects,
            include_status_codes=frozenset(include_status_codes),
            exclude_status_codes=frozenset(exclude_status_codes),
            verify_tls=verify_tls,
            user_agent=user_agent,
            result_predicate=result_predicate,
            session_factory=session_factory,
            raise_on_error=raise_on_error,
            preflight=preflight,
        )

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("FuzzerConfig.url is required")
        if not isinstance(self.wordlist, (Wordlist, WordlistTemplate)):
            object.__setattr__(self, "wordlist", Wordlist(self.wordlist))
        object.__setattr__(self, "headers", dict(self.headers))
        object.__setattr__(self, "extensions", tuple(self.extensions))
        object.__setattr__(
            self, "include_status_codes", frozenset(self.include_status_codes)
        )
        object.__setattr__(
            self, "exclude_status_codes", frozenset(self.exclude_status_codes)
        )


class DirsearchFuzzer:
    def __init__(
        self,
        config: FuzzerConfig,
        *,
        on_result: Callable[[FuzzerResult], Any] | None = None,
        on_not_found: Callable[[FuzzerResult], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
    ) -> None:
        self.config = config
        self.on_result = on_result
        self.on_not_found = on_not_found
        self.on_error = on_error
        self.preflight_result: PreflightResult | None = None

    def run(self) -> list[FuzzerResult]:
        results: list[FuzzerResult] = []
        if self.config.preflight:
            self.preflight_result = self.preflight()
        session = (
            self.config.session_factory()
            if self.config.session_factory
            else requests.Session()
        )
        try:
            session.verify = self.config.verify_tls
            headers = {**DEFAULT_HEADERS, **dict(self.config.headers)}
            if self.config.user_agent:
                headers["user-agent"] = self.config.user_agent

            for path in self._wordlist():
                try:
                    result = self._request(session, headers, path)
                except requests.RequestException as error:
                    if self.on_error:
                        self.on_error(error)
                    if self.config.raise_on_error:
                        raise
                    continue

                if self._is_match(result):
                    results.append(result)
                    if self.on_result:
                        self.on_result(result)
                elif self.on_not_found:
                    self.on_not_found(result)
        finally:
            session.close()
        return results

    def preflight(self) -> PreflightResult:
        profile = PreflightProfile("api", 1, 0.0, 0)
        result = PreflightResult(
            enabled=True,
            applied_profile=profile,
            original_profile=profile,
        )
        session = (
            self.config.session_factory()
            if self.config.session_factory
            else requests.Session()
        )
        try:
            session.verify = self.config.verify_tls
            headers = {**DEFAULT_HEADERS, **dict(self.config.headers)}
            fingerprints = []
            for path in list(self._wordlist())[:4]:
                response = session.get(
                    self._join_url(self.config.url, path),
                    headers=headers,
                    timeout=self.config.timeout,
                    allow_redirects=self.config.follow_redirects,
                )
                fingerprints.append(fingerprint_headers(response.headers))
            result.fingerprint = merge_fingerprints(fingerprints)
        finally:
            session.close()
        return result

    def _wordlist(self) -> Wordlist:
        source = self.config.wordlist
        if isinstance(source, Wordlist):
            return source
        if isinstance(source, WordlistTemplate):
            return Wordlist.from_template(source, extensions=self.config.extensions)
        return Wordlist(source)

    def _request(
        self,
        session: requests.Session,
        headers: Mapping[str, str],
        path: str,
    ) -> FuzzerResult:
        url = self._join_url(self.config.url, path)
        start = time.perf_counter()
        response = session.request(
            self.config.http_method,
            url,
            headers=headers,
            data=self.config.data,
            timeout=self.config.timeout,
            allow_redirects=self.config.follow_redirects,
        )
        body = response.content
        return FuzzerResult(
            url=url,
            path=path,
            status=response.status_code,
            length=int(response.headers.get("content-length") or len(body)),
            content_type=response.headers.get("content-type", "").split(";")[0],
            redirect=response.headers.get("location", ""),
            elapsed=time.perf_counter() - start,
            headers=dict(response.headers),
            body=body,
        )

    def _is_match(self, result: FuzzerResult) -> bool:
        if result.status in self.config.exclude_status_codes:
            return False
        if (
            self.config.include_status_codes
            and result.status not in self.config.include_status_codes
        ):
            return False
        if self.config.result_predicate and not self.config.result_predicate(result):
            return False
        return True

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        parsed = urlsplit(ensure_trailing_path_slash(base_url))
        base_url = urlunsplit(parsed._replace(query="", fragment=""))

        return append_query_string(urljoin(base_url, safequote(path)), parsed.query)
