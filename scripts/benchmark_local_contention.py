#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.connection.native import NativeHTTPBackend
from lib.connection.requester import AsyncRequester, Requester
from lib.core.data import options
from lib.core.exceptions import RequestException


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
    "headers": {"user-agent": "dirsearch-local-contention-benchmark"},
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
    "request_backend": "python",
    "suffixes": (),
    "timeout": 5,
    "uppercase": False,
    "wordlist_backend": "python",
    "wordlist_max_size": 5_000_000,
}


class BenchmarkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    ok_body = b"ok\n"
    miss_body = b"not found\n"

    def do_GET(self) -> None:
        if self.path.startswith("/hit-"):
            self._send(200, self.ok_body)
        else:
            self._send(404, self.miss_body)

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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


def build_paths(count: int, hit_every: int) -> list[str]:
    paths = []
    for index in range(count):
        if hit_every and index % hit_every == 0:
            paths.append(f"hit-{index}")
        else:
            paths.append(f"miss-{index}")
    return paths


def write_wordlist(paths: list[str]) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    with handle:
        for path in paths:
            handle.write(path + "\n")
    return handle.name


def summarize_status(statuses: list[int]) -> dict[str, int]:
    return {str(status): count for status, count in sorted(Counter(statuses).items())}


def summarize_samples(samples: list[dict[str, Any]], requests: int) -> dict[str, Any]:
    elapsed_values = [sample["elapsed_s"] for sample in samples]
    rps_values = [sample["requests_per_s"] for sample in samples]
    return {
        "repeats": len(samples),
        "requests": requests,
        "elapsed_s": {
            "min": min(elapsed_values),
            "median": statistics.median(elapsed_values),
            "max": max(elapsed_values),
        },
        "requests_per_s": {
            "min": min(rps_values),
            "median": statistics.median(rps_values),
            "max": max(rps_values),
        },
        "errors": sum(sample.get("errors", 0) for sample in samples),
        "statuses": summarize_status(
            [
                status
                for sample in samples
                for status, count in sample.get("statuses", {}).items()
                for _ in range(count)
            ]
        ),
        "samples": samples,
    }


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

    statuses = [
        response.status
        for _, response, error in results
        if error is None and response is not None
    ]
    errors = sum(1 for _, _, error in results if error is not None)
    return {
        "elapsed_s": elapsed,
        "requests_per_s": len(paths) / elapsed,
        "errors": errors,
        "statuses": summarize_status(statuses),
    }


def run_direct_benchmarks(
    base_url: str,
    paths: list[str],
    *,
    concurrencies: list[int],
    repeats: int,
    timeout: float,
) -> dict[str, Any]:
    benchmarks = {
        "requests": bench_requests,
        "httpx_workers": bench_httpx,
        "rust_reqwest": bench_rust,
    }
    results = {}
    for concurrency in concurrencies:
        key = str(concurrency)
        results[key] = {}
        for name, benchmark in benchmarks.items():
            samples = [
                benchmark(base_url, paths, concurrency, timeout)
                for _ in range(repeats)
            ]
            summary = summarize_samples(samples, len(paths))
            summary["concurrency"] = concurrency
            results[key][name] = summary
    return results


def run_dirsearch_process(
    base_url: str,
    wordlist: str,
    *,
    request_backend: str,
    threads: int,
    timeout: float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "dirsearch.py"),
        "-u",
        base_url,
        "-w",
        wordlist,
        "-e",
        "txt",
        "--request-backend",
        request_backend,
        "--exclude-status",
        "404",
        "--timeout",
        str(timeout),
        "--retries",
        "0",
        "-t",
        str(threads),
        "-q",
    ]
    time_file = tempfile.NamedTemporaryFile(delete=False)
    time_file.close()
    timed_command = command
    if shutil.which("/usr/bin/time"):
        timed_command = ["/usr/bin/time", "-v", "-o", time_file.name, *command]

    try:
        start = time.perf_counter()
        completed = subprocess.run(
            timed_command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        elapsed = time.perf_counter() - start
        return {
            "returncode": completed.returncode,
            "elapsed_s": elapsed,
            "stderr": completed.stderr.strip(),
            "resource_usage": parse_time_verbose(Path(time_file.name)),
        }
    finally:
        Path(time_file.name).unlink(missing_ok=True)


def parse_time_verbose(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}

    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()

    def int_field(name: str) -> int | None:
        value = fields.get(name)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    return {
        "user_time_s": fields.get("User time (seconds)"),
        "system_time_s": fields.get("System time (seconds)"),
        "cpu_percent": fields.get("Percent of CPU this job got"),
        "max_rss_kb": int_field("Maximum resident set size (kbytes)"),
        "voluntary_context_switches": int_field("Voluntary context switches"),
        "involuntary_context_switches": int_field("Involuntary context switches"),
    }


def run_contention_group(
    base_url: str,
    wordlist: str,
    *,
    request_backend: str,
    processes: int,
    threads: int,
    requests_per_process: int,
    timeout: float,
) -> dict[str, Any]:
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=processes) as executor:
        futures = [
            executor.submit(
                run_dirsearch_process,
                base_url,
                wordlist,
                request_backend=request_backend,
                threads=threads,
                timeout=timeout,
            )
            for _ in range(processes)
        ]
        process_results = [future.result() for future in as_completed(futures)]
    elapsed = time.perf_counter() - start
    total_requests = processes * requests_per_process
    return {
        "backend": request_backend,
        "processes": processes,
        "threads_per_process": threads,
        "total_requests": total_requests,
        "elapsed_s": elapsed,
        "aggregate_requests_per_s": total_requests / elapsed,
        "failed_processes": sum(1 for result in process_results if result["returncode"] != 0),
        "process_results": process_results,
    }


def run_contention_benchmarks(
    base_url: str,
    wordlist: str,
    *,
    process_counts: list[int],
    repeats: int,
    threads: int,
    requests_per_process: int,
    timeout: float,
) -> dict[str, Any]:
    results = {}
    for processes in process_counts:
        key = str(processes)
        results[key] = {}
        for backend in ("python", "native"):
            samples = [
                run_contention_group(
                    base_url,
                    wordlist,
                    request_backend=backend,
                    processes=processes,
                    threads=threads,
                    requests_per_process=requests_per_process,
                    timeout=timeout,
                )
                for _ in range(repeats)
            ]
            elapsed_values = [sample["elapsed_s"] for sample in samples]
            rps_values = [sample["aggregate_requests_per_s"] for sample in samples]
            results[key][backend] = {
                "repeats": repeats,
                "processes": processes,
                "threads_per_process": threads,
                "total_requests": processes * requests_per_process,
                "elapsed_s": {
                    "min": min(elapsed_values),
                    "median": statistics.median(elapsed_values),
                    "max": max(elapsed_values),
                },
                "aggregate_requests_per_s": {
                    "min": min(rps_values),
                    "median": statistics.median(rps_values),
                    "max": max(rps_values),
                },
                "failed_processes": sum(sample["failed_processes"] for sample in samples),
                "samples": samples,
            }
    return results


def parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled local HTTP benchmark and dirsearch contention test")
    parser.add_argument("--base-url", help="Existing target URL. If omitted, a local Python test server is started.")
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--contention-requests", type=int, default=1000)
    parser.add_argument("--concurrencies", default="12,25,50")
    parser.add_argument("--process-counts", default="1,2,4,8")
    parser.add_argument("--threads-per-process", type=int, default=12)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--hit-every", type=int, default=20)
    args = parser.parse_args()

    direct_paths = build_paths(args.requests, args.hit_every)
    contention_paths = build_paths(args.contention_requests, args.hit_every)
    wordlist = write_wordlist(contention_paths)
    try:
        if args.base_url:
            server_context = contextlib.nullcontext(args.base_url.rstrip("/") + "/")
        else:
            server_context = local_http_server()

        with server_context as base_url:
            result = {
                "target": base_url,
                "direct": run_direct_benchmarks(
                    base_url,
                    direct_paths,
                    concurrencies=parse_int_list(args.concurrencies),
                    repeats=args.repeats,
                    timeout=args.timeout,
                ),
                "contention": run_contention_benchmarks(
                    base_url,
                    wordlist,
                    process_counts=parse_int_list(args.process_counts),
                    repeats=args.repeats,
                    threads=args.threads_per_process,
                    requests_per_process=args.contention_requests,
                    timeout=args.timeout,
                ),
            }
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        Path(wordlist).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
