"""Diagnostic CPU stage timings; run throughput benchmarks without this wrapper."""
from __future__ import annotations

import argparse
import json
import runpy
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class StageTimer:
    def __init__(self, clock=time.thread_time_ns):
        self.clock = clock
        self.totals = {}
        self.frames = threading.local()
        self.lock = threading.Lock()

    def wrap(self, name, function):
        def measured(*args, **kwargs):
            try:
                frames = self.frames.stack
            except AttributeError:
                frames = self.frames.stack = []
            child_time = [0]
            frames.append(child_time)
            start = self.clock()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = self.clock() - start
                frames.pop()
                if frames:
                    frames[-1][0] += elapsed
                with self.lock:
                    row = self.totals.setdefault(name, dict(calls=0, inclusive_ns=0, exclusive_ns=0))
                    row['calls'] += 1
                    row['inclusive_ns'] += elapsed
                    row['exclusive_ns'] += elapsed - child_time[0]
        return measured


@contextmanager
def profile_stages():
    from lib.connection.native import NativeHTTPBackend
    from lib.core.fuzzer import BaseFuzzer, NativeFuzzer
    from lib.core.scanner import BaseScanner
    from lib.connection import response
    from lib.utils import diff

    timer = StageTimer()
    targets = [
        (diff, 'normalize_dynamic_content', diff.normalize_dynamic_content, 'normalization'),
        (diff, 'normalized_content_similarity', diff.normalized_content_similarity, 'similarity'),
        (diff.DynamicContentParser, 'compare_to', diff.DynamicContentParser.compare_to, 'patterns'),
        (diff.DynamicContentParser, '_recalculate', diff.DynamicContentParser._recalculate, 'calibration'),
        (NativeHTTPBackend, '_make_scan_chunk', NativeHTTPBackend._make_scan_chunk, 'response_objects'),
        (NativeFuzzer, '_process_native_chunk', NativeFuzzer._process_native_chunk, 'dispatch'),
        (BaseFuzzer, 'is_excluded', BaseFuzzer.is_excluded, 'explicit_filters'),
        (BaseFuzzer, 'is_auto_calibrated', BaseFuzzer.is_auto_calibrated, 'auto_calibration'),
        (BaseFuzzer, 'is_filter_threshold_reached', BaseFuzzer.is_filter_threshold_reached, 'duplicate_threshold'),
        (BaseScanner, 'classify', BaseScanner.classify, 'wildcard_decision'),
    ]
    with ExitStack() as stack:
        for owner, attribute, original, name in targets:
            stack.enter_context(patch.object(owner, attribute, timer.wrap(name, original)))
        stack.enter_context(patch.object(response, 'normalize_dynamic_content', diff.normalize_dynamic_content))
        stack.enter_context(patch.object(BaseFuzzer, 'response_fingerprint',
                                         staticmethod(timer.wrap('fingerprint', BaseFuzzer.response_fingerprint))))
        yield timer.totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('scan_args', nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    scan_args = arguments.scan_args
    if scan_args[:1] == ['--']:
        scan_args = scan_args[1:]
    if not scan_args:
        parser.error('provide dirsearch arguments after --')
    sys.argv = [str(ROOT / 'dirsearch.py'), *scan_args]
    started = time.perf_counter()
    with profile_stages() as stages:
        try:
            runpy.run_path(sys.argv[0], run_name='__main__')
        finally:
            arguments.output.write_text(json.dumps(dict(
                diagnostic=True, wall_s=time.perf_counter() - started, stages=stages,
                note='Instrumentation changes timing. Measure RPS in separate uninstrumented runs.',
            ), indent=2))


if __name__ == '__main__':
    main()
