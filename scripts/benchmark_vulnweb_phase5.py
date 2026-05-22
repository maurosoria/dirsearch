#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.connection.requester import AsyncRequester, Requester
from lib.connection.native import NativeHTTPBackend
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import RequestException, WordlistBackendUnavailableError


TARGETS = {
    "php": {
        "url": "http://testphp.vulnweb.com/",
        "extensions": ("php",),
    },
    "html5": {
        "url": "http://testhtml5.vulnweb.com/",
        "extensions": ("html", "js"),
    },
    "asp": {
        "url": "http://testasp.vulnweb.com/",
        "extensions": ("asp",),
    },
    "aspx": {
        "url": "http://testaspnet.vulnweb.com/",
        "extensions": ("aspx",),
    },
    "rest": {
        "url": "http://rest.vulnweb.com/",
        "extensions": ("json",),
    },
    "testfire": {
        "url": "http://demo.testfire.net/",
        "extensions": ("jsp", "html"),
    },
    "zero": {
        "url": "http://zero.webappsecurity.com/",
        "extensions": ("html",),
    },
}

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
    "headers": {"user-agent": "dirsearch-phase5-benchmark"},
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
    "uppercase": False,
    "wordlist_max_size": 5_000_000,
}

SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@/?#-]+$")


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


def generate_paths(
    backend: str,
    wordlist: str,
    extensions: tuple[str, ...],
    limit: int,
) -> tuple[list[str], dict[str, Any]]:
    start = time.perf_counter()
    with benchmark_options(
        extensions=extensions,
        thread_count=1,
        timeout=5,
        wordlist_backend=backend,
    ):
        dictionary = Dictionary(files=[wordlist])
        paths = [path for path in dictionary if SAFE_PATH_RE.fullmatch(path)]
    elapsed = time.perf_counter() - start
    return paths[:limit], {
        "backend": backend,
        "generated": len(dictionary),
        "safe": len(paths),
        "selected": min(limit, len(paths)),
        "elapsed_s": elapsed,
        "entries_per_s": len(dictionary) / elapsed,
    }


def summarize_status(statuses: list[int]) -> dict[str, int]:
    return {str(status): count for status, count in sorted(Counter(statuses).items())}


def bench_requests(base_url: str, paths: list[str], concurrency: int, timeout: float) -> dict[str, Any]:
    with benchmark_options(thread_count=concurrency, timeout=timeout):
        requester = Requester()
        requester.set_url(base_url)
        statuses = []
        errors = 0
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(requester.request, path) for path in paths]
            for future in as_completed(futures):
                try:
                    statuses.append(future.result().status)
                except RequestException:
                    errors += 1
        elapsed = time.perf_counter() - start

    return {
        "backend": "requests",
        "requests": len(paths),
        "concurrency": concurrency,
        "elapsed_s": elapsed,
        "requests_per_s": len(paths) / elapsed,
        "errors": errors,
        "statuses": summarize_status(statuses),
    }


async def _bench_httpx_workers(base_url: str, paths: list[str], concurrency: int, timeout: float) -> dict[str, Any]:
    with benchmark_options(thread_count=concurrency, timeout=timeout):
        requester = AsyncRequester()
        requester.set_url(base_url)
        queue = asyncio.Queue()
        for path in paths:
            queue.put_nowait(path)

        statuses = []
        errors = 0

        async def worker() -> None:
            nonlocal errors
            while True:
                try:
                    path = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    response = await requester.request(path)
                    statuses.append(response.status)
                except RequestException:
                    errors += 1
                finally:
                    queue.task_done()

        start = time.perf_counter()
        try:
            await asyncio.gather(*(worker() for _ in range(concurrency)))
        finally:
            await requester.session.aclose()
            if requester.replay_session is not None:
                await requester.replay_session.aclose()
        elapsed = time.perf_counter() - start

    return {
        "backend": "httpx-workers",
        "requests": len(paths),
        "concurrency": concurrency,
        "elapsed_s": elapsed,
        "requests_per_s": len(paths) / elapsed,
        "errors": errors,
        "statuses": summarize_status(statuses),
    }


def bench_httpx(base_url: str, paths: list[str], concurrency: int, timeout: float) -> dict[str, Any]:
    return asyncio.run(_bench_httpx_workers(base_url, paths, concurrency, timeout))


def bench_rust(base_url: str, paths: list[str], concurrency: int, timeout: float) -> dict[str, Any]:
    with benchmark_options(thread_count=concurrency, timeout=timeout):
        backend = NativeHTTPBackend()
        start = time.perf_counter()
        results = list(backend.scan(base_url, paths))
        elapsed = time.perf_counter() - start
    statuses = [response.status for _, response, error in results if error is None and response.status]
    errors = sum(1 for _, _, error in results if error is not None)
    return {
        "backend": "rust-reqwest",
        "requests": len(paths),
        "concurrency": concurrency,
        "elapsed_s": elapsed,
        "requests_per_s": len(paths) / elapsed,
        "errors": errors,
        "statuses": summarize_status(statuses),
    }


def run_target(
    name: str,
    *,
    wordlist: str,
    limit: int,
    concurrency: int,
    timeout: float,
) -> dict[str, Any]:
    target = TARGETS[name]
    paths, python_wordlist = generate_paths(
        "python",
        wordlist,
        target["extensions"],
        limit,
    )
    result = {
        "url": target["url"],
        "extensions": target["extensions"],
        "wordlist_python": python_wordlist,
        "requests": bench_requests(target["url"], paths, concurrency, timeout),
        "httpx_workers": bench_httpx(target["url"], paths, concurrency, timeout),
    }

    try:
        native_paths, native_wordlist = generate_paths(
            "native",
            wordlist,
            target["extensions"],
            limit,
        )
        result["wordlist_native"] = native_wordlist
        result["native_path_parity"] = native_paths == paths
        result["rust_reqwest"] = bench_rust(target["url"], native_paths, concurrency, timeout)
    except (ImportError, WordlistBackendUnavailableError) as error:
        result["native_error"] = str(error)

    return result


def preflight(url: str, timeout: float) -> tuple[bool, str]:
    try:
        request = urllib.request.Request(
            url,
            headers={"user-agent": "dirsearch-phase5-benchmark"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, str(response.status)
    except Exception as error:
        return False, str(error)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Phase 5 against Acunetix/Vulnweb test sites")
    parser.add_argument("--wordlist", default="db/dicc.txt")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--no-preflight", action="store_true")
    parser.add_argument(
        "--targets",
        default="asp,aspx,rest,php,html5",
        help="Comma-separated target names or 'all': php,asp,aspx,rest,html5,testfire,zero",
    )
    args = parser.parse_args()

    results = {}
    target_names = (
        list(TARGETS)
        if args.targets.strip() == "all"
        else [item.strip() for item in args.targets.split(",") if item.strip()]
    )
    for name in target_names:
        if name not in TARGETS:
            raise SystemExit(f"Unknown target: {name}")
        if not args.no_preflight:
            ok, detail = preflight(TARGETS[name]["url"], min(args.timeout, 5.0))
            if not ok:
                results[name] = {
                    "url": TARGETS[name]["url"],
                    "skipped": True,
                    "preflight_error": detail,
                }
                continue
        results[name] = run_target(
            name,
            wordlist=args.wordlist,
            limit=args.limit,
            concurrency=args.concurrency,
            timeout=args.timeout,
        )

    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
