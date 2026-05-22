#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.connection.requester import AsyncRequester, Requester
from lib.connection.native import NativeHTTPBackend
from lib.core.data import options
from lib.core.dictionary import Dictionary


DEFAULT_OPTIONS: dict[str, Any] = {
    "auth": None,
    "auth_type": None,
    "capitalization": False,
    "cert_file": None,
    "data": None,
    "delay": 0.0,
    "exclude_extensions": (),
    "follow_redirects": False,
    "force_extensions": False,
    "headers": {},
    "http_method": "GET",
    "key_file": None,
    "lowercase": False,
    "max_rate": 0,
    "max_retries": 0,
    "network_interface": None,
    "overwrite_extensions": False,
    "prefixes": (),
    "proxies": [],
    "proxy_auth": None,
    "random_agents": False,
    "suffixes": (),
    "timeout": 5,
    "uppercase": False,
    "wordlist_backend": "python",
    "wordlist_max_size": 5_000_000,
}


class BenchmarkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    body = b"ok\n"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextlib.contextmanager
def local_http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), BenchmarkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextlib.contextmanager
def benchmark_options(**overrides: Any):
    original = dict(options)
    options.update(DEFAULT_OPTIONS)
    options.update(overrides)
    try:
        yield
    finally:
        options.clear()
        options.update(original)


def timed(callable_, repeats: int) -> dict[str, float]:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        callable_()
        samples.append(time.perf_counter() - start)

    return {
        "min_s": min(samples),
        "median_s": statistics.median(samples),
        "max_s": max(samples),
    }


def bench_wordlist(files: list[str], extensions: tuple[str, ...], repeats: int) -> dict[str, Any]:
    return bench_wordlist_backend("python", files, extensions, repeats)


def bench_wordlist_backend(
    backend: str,
    files: list[str],
    extensions: tuple[str, ...],
    repeats: int,
) -> dict[str, Any]:
    entries = 0
    peaks = []
    samples = []

    with benchmark_options(extensions=extensions, wordlist_backend=backend):
        for _ in range(repeats):
            tracemalloc.start()
            start = time.perf_counter()
            dictionary = Dictionary(files=files)
            elapsed = time.perf_counter() - start
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            entries = len(dictionary)
            samples.append(elapsed)
            peaks.append(peak)

    return {
        "backend": backend,
        "entries": entries,
        "files": files,
        "repeats": repeats,
        "min_s": min(samples),
        "median_s": statistics.median(samples),
        "max_s": max(samples),
        "peak_mib": max(peaks) / 1024 / 1024,
        "entries_per_s": entries / statistics.median(samples),
    }


def bench_native_http(base_url: str, paths: list[str], concurrency: int) -> dict[str, Any]:
    with benchmark_options(thread_count=concurrency):
        backend = NativeHTTPBackend()
        start = time.perf_counter()
        results = list(backend.scan(base_url, paths))
        elapsed = time.perf_counter() - start

    responses = [response for _, response, error in results if error is None]
    return {
        "backend": "rust-reqwest",
        "concurrency": concurrency,
        "requests": len(paths),
        "elapsed_s": elapsed,
        "requests_per_s": len(paths) / elapsed,
        "errors": sum(1 for _, _, error in results if error is not None),
        "ok": sum(1 for response in responses if response.status == 200),
    }


def bench_sync_requests(base_url: str, paths: list[str], concurrency: int) -> dict[str, Any]:
    with benchmark_options(thread_count=concurrency):
        requester = Requester()
        requester.set_url(base_url)

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(requester.request, path) for path in paths]
            for future in as_completed(futures):
                future.result()
        elapsed = time.perf_counter() - start

    return {
        "backend": "requests",
        "concurrency": concurrency,
        "requests": len(paths),
        "elapsed_s": elapsed,
        "requests_per_s": len(paths) / elapsed,
    }


async def _bench_async_task_per_path(base_url: str, paths: list[str], concurrency: int) -> None:
    with benchmark_options(thread_count=concurrency):
        requester = AsyncRequester()
        requester.set_url(base_url)
        sem = asyncio.Semaphore(concurrency)

        async def run(path: str) -> None:
            async with sem:
                await requester.request(path)

        try:
            await asyncio.gather(*(run(path) for path in paths))
        finally:
            await requester.session.aclose()
            if requester.replay_session is not None:
                await requester.replay_session.aclose()


async def _bench_async_workers(base_url: str, paths: list[str], concurrency: int) -> None:
    with benchmark_options(thread_count=concurrency):
        requester = AsyncRequester()
        requester.set_url(base_url)
        queue = asyncio.Queue()
        for path in paths:
            queue.put_nowait(path)

        async def worker() -> None:
            while True:
                try:
                    path = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await requester.request(path)
                finally:
                    queue.task_done()

        try:
            await asyncio.gather(*(worker() for _ in range(concurrency)))
        finally:
            await requester.session.aclose()
            if requester.replay_session is not None:
                await requester.replay_session.aclose()


def bench_async_requests(
    base_url: str,
    paths: list[str],
    concurrency: int,
    mode: str,
) -> dict[str, Any]:
    target = _bench_async_workers if mode == "workers" else _bench_async_task_per_path
    start = time.perf_counter()
    asyncio.run(target(base_url, paths, concurrency))
    elapsed = time.perf_counter() - start
    return {
        "backend": f"httpx-{mode}",
        "concurrency": concurrency,
        "requests": len(paths),
        "elapsed_s": elapsed,
        "requests_per_s": len(paths) / elapsed,
    }


def build_paths(count: int) -> list[str]:
    return [f"bench-{index}" for index in range(count)]


def build_template_file(path_count: int) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    with handle:
        for index in range(path_count):
            handle.write(f"bench-{index}-%EXT%\n")
    return handle.name


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 performance baseline")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--wordlist-lines", type=int, default=2500)
    parser.add_argument("--wordlist-repeats", type=int, default=3)
    parser.add_argument("--include-native", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    generated_wordlist = build_template_file(args.wordlist_lines)
    try:
        results = {
            "wordlist_dicc": bench_wordlist(
                ["db/dicc.txt"],
                ("php", "json", "txt"),
                args.wordlist_repeats,
            ),
            "wordlist_template": bench_wordlist(
                [generated_wordlist],
                ("php", "json", "txt"),
                args.wordlist_repeats,
            ),
        }

        if args.include_native:
            try:
                results["native_wordlist_dicc"] = bench_wordlist_backend(
                    "native",
                    ["db/dicc.txt"],
                    ("php", "json", "txt"),
                    args.wordlist_repeats,
                )
                results["native_wordlist_template"] = bench_wordlist_backend(
                    "native",
                    [generated_wordlist],
                    ("php", "json", "txt"),
                    args.wordlist_repeats,
                )
            except Exception as error:
                results["native_wordlist_error"] = str(error)

        paths = build_paths(args.requests)
        with local_http_server() as base_url:
            results["http_requests"] = bench_sync_requests(
                base_url,
                paths,
                args.concurrency,
            )
            results["httpx_task_per_path"] = bench_async_requests(
                base_url,
                paths,
                args.concurrency,
                "task-per-path",
            )
            results["httpx_workers"] = bench_async_requests(
                base_url,
                paths,
                args.concurrency,
                "workers",
            )
            if args.include_native:
                try:
                    results["rust_http"] = bench_native_http(
                        base_url,
                        paths,
                        args.concurrency,
                    )
                except Exception as error:
                    results["rust_http_error"] = str(error)

        if args.as_json:
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            for name, result in results.items():
                print(f"{name}:")
                for key, value in result.items():
                    print(f"  {key}: {value}")
    finally:
        Path(generated_wordlist).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
