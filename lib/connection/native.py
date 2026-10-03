from __future__ import annotations

import threading

from collections.abc import Callable, Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from lib.connection.ip_overrides import IPOverrides
from lib.connection.proxy import (
    PROXY_AUTHENTICATION_REQUIRED,
    add_proxy_authentication,
    format_proxy_error,
    is_proxy_authentication_error,
    is_proxy_connect_rejection,
    proxy_error_status,
)
from lib.connection.response import NativeResponse
from lib.core.request_config import RequestConfig
from lib.core.exceptions import RequestException
from lib.core.native_runtime import (
    get_native_backend_install_error,
    get_native_extension_version_error,
)
from lib.core.request_backend import (
    CLIENT_CERTIFICATE_PAIR_ERROR,
    NATIVE_PROXY_SCHEME_ERROR,
    NATIVE_SOCKS4_AUTH_ERROR,
    get_native_authentication_error,
)
from lib.core.settings import (
    MAX_REDIRECTS,
    MAX_RESPONSE_SIZE,
    PROXY_SCHEMES,
    SCRIPT_PATH,
)
from lib.core.wordlist_backend import NativeWordlistChunk
from lib.utils.file import FileUtils
from lib.utils.mimetype import guess_mimetype


@dataclass(frozen=True, slots=True)
class NativeScanEvent:
    """One actionable Rust result, indexed into the original path chunk."""

    request_index: int
    path: str
    response: NativeResponse | None
    error: RequestException | None


@dataclass(frozen=True, slots=True)
class NativeScanChunk:
    """Actionable results from the completed range [start_index, end_index)."""

    start_index: int
    end_index: int
    events: tuple[NativeScanEvent, ...]


class NativeHTTPBackend:
    def __init__(
        self,
        config: RequestConfig,
        *,
        filter_options: Mapping[str, Any],
        proxy_override: str | None = None,
        session: Any | None = None,
        auth_override: tuple[str, str] | None = None,
        ip_overrides: IPOverrides | None = None,
    ) -> None:
        try:
            import dirsearch_native
        except ImportError as e:
            raise RequestException(get_native_backend_install_error()) from e

        if version_error := get_native_extension_version_error(dirsearch_native):
            raise RequestException(version_error)

        self.config = config
        # Filters are supplied by orchestration, independently of request policy.
        self._filter_options = deepcopy(dict(filter_options))
        self._native = dirsearch_native
        self._engine = None
        self._engine_config = None
        self._filter_config = None
        self._empty_filter_config = None
        self._proxy_override = proxy_override
        self._ip_overrides = (
            ip_overrides if ip_overrides is not None else IPOverrides()
        )
        self._session = (
            session if session is not None else self._native.NativeHttpSession()
        )
        self._auth_type, self._auth_credential = auth_override or (
            (self.config.auth_type, self.config.auth)
            if self.config.auth
            else ("", "")
        )
        self._client_certificate, self._client_key = self._load_client_identity()
        self._random_user_agents = self._load_random_user_agents()
        self._cancel_lock = threading.Lock()
        # Preserve cancellation requested before lazy engine creation.
        self._cancel_generation = 0
        self._consumed_cancel_generation = 0

    def _get_engine(self):
        proxies = (
            self._normalize_proxy_urls([self._proxy_override], self.config.proxy_auth)
            if self._proxy_override is not None
            else self._proxy_urls(self.config)
        )
        body = self._request_body()
        headers = [
            (name, value)
            for name, value in self.config.headers
            if not (
                (self._random_user_agents and name.lower() == "user-agent")
                or (self._auth_type and name.lower() == "authorization")
            )
        ]
        if body and not any(name.lower() == "content-type" for name, _ in headers):
            headers.append(("content-type", guess_mimetype(self.config.body)))

        config = {
            "concurrency": self.config.concurrency,
            "timeout_secs": self.config.timeout,
            "max_rate": self.config.max_rate,
            "delay_secs": self.config.delay,
            "headers": headers,
            "proxies": proxies,
            "follow_redirects": self.config.follow_redirects,
            "max_redirects": MAX_REDIRECTS,
            "method": self.config.method,
            "body": body,
            "client_certificate": self._client_certificate,
            "client_key": self._client_key,
            "auth_type": self._auth_type,
            "auth_credential": self._auth_credential,
            "random_user_agents": self._random_user_agents,
            "network_interface": self.config.network_interface or "",
            "connection_overrides": self._ip_overrides.connection_overrides(),
        }
        if self._engine is None or config != self._engine_config:
            try:
                self._engine = self._native.NativeHttpEngine(
                    **config,
                    session=self._session,
                )
            except RuntimeError as error:
                raise RequestException(str(error)) from error
            self._engine_config = config
        return self._engine

    @property
    def session(self) -> Any:
        """Opaque Rust state shared with engines created for replay requests."""

        return self._session

    @property
    def rate(self) -> int:
        return self._session.rate()

    def set_origin_authentication(
        self, auth_type: str, credential: str
    ) -> None:
        self._auth_type = auth_type
        self._auth_credential = credential

    def _request_body(self) -> bytes:
        data = self.config.body
        if data is None:
            return b""
        if isinstance(data, str):
            return data.encode("utf-8")
        return bytes(data)

    def _load_client_identity(self) -> tuple[bytes, bytes]:
        if bool(self.config.cert_file) != bool(self.config.key_file):
            raise RequestException(CLIENT_CERTIFICATE_PAIR_ERROR)
        if not self.config.cert_file:
            return b"", b""
        try:
            certificate = FileUtils.read_bytes(self.config.cert_file)
            key = FileUtils.read_bytes(self.config.key_file)
        except OSError as error:
            raise RequestException(
                f"Could not read client certificate or private key: {error}"
            ) from error
        if not certificate or not key:
            raise RequestException(
                "Client certificate and private key files must not be empty"
            )
        return certificate, key

    def _load_random_user_agents(self) -> list[str]:
        if not self.config.random_agents:
            return []
        try:
            return FileUtils.get_lines(
                FileUtils.build_path(SCRIPT_PATH, "db", "user-agents.txt")
            )
        except OSError as error:
            raise RequestException(
                f"Could not read random User-Agent list: {error}"
            ) from error

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

    def close(self) -> None:
        """Cancel active work and release the persistent Rust runtime and clients."""

        with self._cancel_lock:
            if self._engine is not None:
                self._engine.cancel()
            self._engine = None
            self._engine_config = None

    def scan(
        self,
        base_url: str,
        paths: Iterable[str],
        query: str = "",
    ) -> Iterator[tuple[str, NativeResponse | None, RequestException | None]]:
        raw_paths, results = self._scan(base_url, paths, query)

        for path, result in zip(raw_paths, results):
            response, error = self._convert_result(base_url, result)
            yield path, response, error

    def scan_chunks(
        self,
        base_url: str,
        paths: list[str] | NativeWordlistChunk,
        callback: Callable[[NativeScanChunk], Any],
        query: str = "",
    ) -> int:
        """Deliver ordered compact ranges while Rust is still scanning."""

        raw_paths = paths
        with self._cancel_lock:
            engine = self._get_engine()
            cancel_generation = self._cancel_generation
            if cancel_generation != self._consumed_cancel_generation:
                engine.cancel()

        def process_chunk(
            start_index: int,
            end_index: int,
            results: list[Any],
        ) -> None:
            callback(
                self._make_scan_chunk(
                    base_url,
                    raw_paths,
                    results,
                    start_index=start_index,
                    end_index=end_index,
                )
            )

        scan_options = {
            "query": query,
            "max_retries": self.config.max_retries,
            "max_body_size": MAX_RESPONSE_SIZE,
            "filter_config": self._get_filter_config(True),
        }
        try:
            if isinstance(raw_paths, NativeWordlistChunk):
                return engine.scan_owned_chunks(
                    base_url,
                    raw_paths.native,
                    process_chunk,
                    **scan_options,
                )
            return engine.scan_chunks(
                base_url,
                raw_paths,
                process_chunk,
                **scan_options,
            )
        finally:
            with self._cancel_lock:
                self._consumed_cancel_generation = self._cancel_generation

    def _make_scan_chunk(
        self,
        base_url: str,
        raw_paths: list[str] | NativeWordlistChunk,
        results: Iterable[Any],
        *,
        start_index: int,
        end_index: int,
    ) -> NativeScanChunk:
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
            response, error = self._convert_result(base_url, result)
            events.append(
                NativeScanEvent(
                    request_index,
                    (
                        raw_paths.path_at(request_index)
                        if isinstance(raw_paths, NativeWordlistChunk)
                        else raw_paths[request_index]
                    ),
                    response,
                    error,
                )
            )

        return NativeScanChunk(start_index, end_index, tuple(events))

    def scan_unfiltered(
        self,
        base_url: str,
        path: str,
        query: str = "",
    ) -> tuple[NativeResponse | None, RequestException | None]:
        _raw_paths, results = self._scan(
            base_url,
            [path],
            query,
            apply_filters=False,
        )
        if not results:
            return None, RequestException("Native request was cancelled")
        return self._convert_result(base_url, results[0])

    def _scan(
        self,
        base_url: str,
        paths: Iterable[str] | NativeWordlistChunk,
        query: str,
        *,
        apply_filters: bool = True,
    ) -> tuple[list[str], list[Any]]:
        raw_paths = list(paths)
        with self._cancel_lock:
            engine = self._get_engine()
            cancel_generation = self._cancel_generation
            if cancel_generation != self._consumed_cancel_generation:
                engine.cancel()

        scan_options = {
            "query": query,
            "max_retries": self.config.max_retries,
            "max_body_size": MAX_RESPONSE_SIZE,
            "filter_config": self._get_filter_config(apply_filters),
        }
        try:
            results = engine.scan(base_url, raw_paths, **scan_options)
        finally:
            with self._cancel_lock:
                self._consumed_cancel_generation = self._cancel_generation

        return raw_paths, results

    def _convert_result(
        self,
        base_url: str,
        result: Any,
    ) -> tuple[NativeResponse | None, RequestException | None]:
        if result.error is not None:
            error_message = result.error
            if (
                self._using_proxy
                and (
                    proxy_error_status(error_message) is not None
                    or is_proxy_authentication_error(error_message)
                    or is_proxy_connect_rejection(error_message)
                )
            ):
                error_message = format_proxy_error(error_message)
            return None, RequestException(error_message)

        if self._using_proxy and result.status == PROXY_AUTHENTICATION_REQUIRED:
            return None, RequestException("Proxy authentication required")

        return (
            NativeResponse(
                base_url + result.path,
                result.status,
                result.headers,
                result.body,
                result.elapsed_ms / 1000,
                length=result.length,
                filtered=result.filtered,
                filter_reason=result.filter_reason,
                body_complete=result.body_complete,
                history=(
                    result.history
                    if self._engine_config is not None
                    and self._engine_config["follow_redirects"]
                    else ()
                ),
                final_url=result.final_url,
            ),
            None,
        )

    @staticmethod
    def _proxy_urls(config: RequestConfig) -> list[str]:
        return NativeHTTPBackend._normalize_proxy_urls(config.proxies, config.proxy_auth)

    @staticmethod
    def _normalize_proxy_urls(
        proxy_values: Iterable[str], proxy_auth: str | None
    ) -> list[str]:
        proxies = []
        for proxy in proxy_values:
            if "://" not in proxy:
                proxy = f"http://{proxy}"
            elif not proxy.lower().startswith(PROXY_SCHEMES):
                raise RequestException(NATIVE_PROXY_SCHEME_ERROR)

            parsed = urlsplit(proxy)
            if parsed.scheme.lower() in ("socks4", "socks4a") and (
                proxy_auth or parsed.username is not None
            ):
                raise RequestException(NATIVE_SOCKS4_AUTH_ERROR)

            proxy = add_proxy_authentication(proxy, proxy_auth)
            proxies.append(proxy)

        return proxies

    @property
    def _using_proxy(self) -> bool:
        return self._proxy_override is not None or bool(self.config.proxies)

    def _get_filter_config(self, apply_filters: bool):
        if not apply_filters:
            if self._empty_filter_config is None:
                self._empty_filter_config = self._native.NativeFilterConfig()
            return self._empty_filter_config
        if self._filter_config is None:
            self._filter_config = self._native.NativeFilterConfig(
                **self._filter_options
            )
        return self._filter_config


class NativeRequester:
    """Minimal requester facade used by native scans and calibration."""

    def __init__(
        self, config: RequestConfig, *, filter_options: Mapping[str, Any]
    ) -> None:
        self.config = config
        self._filter_options = deepcopy(dict(filter_options))
        self._url = ""
        self._query = ""
        self._configured_auth = (
            (self.config.auth_type, self.config.auth)
            if self.config.auth
            else ("", "")
        )
        self._origin_auth = self._configured_auth
        self._ip_overrides = IPOverrides()
        # Controller creates the requester before entering its per-target error
        # handler. Delay the optional extension import until a scan actually
        # starts so a missing build is reported as a normal request error.
        self.backend: NativeHTTPBackend | None = None

    def get_backend(self) -> NativeHTTPBackend:
        if self.backend is None:
            self.backend = NativeHTTPBackend(
                self.config,
                filter_options=self._filter_options,
                auth_override=self._origin_auth,
                ip_overrides=self._ip_overrides,
            )
        return self.backend

    @property
    def rate(self) -> int:
        return 0 if self.backend is None else self.backend.rate

    def set_url(self, url: str) -> None:
        self._url = url

    def set_query(self, query: str) -> None:
        self._query = query

    def set_ip(self, host: str, port: int, ip_address: str) -> None:
        """Force a connection IP while preserving the target Host and SNI."""
        self._ip_overrides.set_override(host, port, ip_address)

    def reset_auth(self) -> None:
        self._set_origin_authentication(*self._configured_auth)

    def set_auth(self, auth_type: str, credential: str) -> None:
        if error := get_native_authentication_error(auth_type):
            raise RequestException(error)
        self._set_origin_authentication(auth_type, credential)

    def _set_origin_authentication(
        self, auth_type: str, credential: str
    ) -> None:
        self._origin_auth = (auth_type, credential)
        if self.backend is not None:
            self.backend.set_origin_authentication(auth_type, credential)

    def request(self, path: str, proxy: str | None = None) -> NativeResponse:
        if proxy:
            origin_backend = self.get_backend()
            backend = NativeHTTPBackend(
                self.config,
                filter_options=self._filter_options,
                proxy_override=proxy,
                session=origin_backend.session,
                auth_override=self._origin_auth,
            )
        else:
            backend = self.get_backend()
        response, error = backend.scan_unfiltered(self._url, path, self._query)
        if error is not None:
            raise error
        if response is None:
            raise RequestException("Native request returned no response")
        return response

    def close(self) -> None:
        if self.backend is None:
            return
        self.backend.close()
        self.backend = None
