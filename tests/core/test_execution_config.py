import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.filter_config import FilterConfig
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from lib.core.wordlist_config import WordlistConfig


def make_fuzzer(engine, config, dictionary=None):
    return engine(
        SimpleNamespace(backend=None), dictionary,
        filter_config=FilterConfig(), discovery_config=DiscoveryConfig(),
        execution_config=config,
        match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
    )


def make_dictionary(paths):
    dictionary = Dictionary(WordlistConfig())
    dictionary.__setstate__((list(paths), 0, [], 0))
    return dictionary


class TestExecutionConfig(TestCase):
    def test_config_freezes_statuses_and_reads_only_supplied_options(self):
        statuses = {429, 503}
        values = {
            "thread_count": 3, "delay": 0.25, "max_time": 10,
            "target_max_time": 2.5, "skip_on_status": statuses, "exit_on_error": True,
        }
        with patch.dict(options, {}, clear=True):
            config = ExecutionConfig.from_options(values)
        statuses.clear()
        values["thread_count"] = 99
        self.assertEqual(config, ExecutionConfig(
            concurrency=3, delay=0.25, max_time=10, target_max_time=2.5,
            skip_on_status={429, 503}, exit_on_error=True,
        ))
        with self.assertRaises(FrozenInstanceError):
            config.concurrency = 1
        self.assertEqual(ExecutionConfig().skip_on_status, frozenset())

    def test_thread_count_and_delay_are_owned_by_each_fuzzer(self):
        for count, delay in ((1, 0), (3, 0.25)):
            with self.subTest(concurrency=count, delay=delay):
                dictionary = make_dictionary(["one", "two"])
                fuzzer = make_fuzzer(Fuzzer, ExecutionConfig(concurrency=count, delay=delay), dictionary)
                fuzzer.scan = Mock()
                with (
                    patch.dict(options, {}, clear=True),
                    patch("lib.core.fuzzer.time.sleep") as sleep,
                ):
                    fuzzer.setup_threads()
                    self.assertEqual(len(fuzzer._threads), count)
                    # Run the worker body deterministically without starting
                    # background threads; the existing lifecycle tests drain real workers.
                    fuzzer.play()
                    fuzzer.thread_proc()
                self.assertEqual([call.args[0] for call in fuzzer.scan.call_args_list], ["one", "two"])
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [delay] * 3)
                self.assertEqual(dictionary.__getstate__(), (["one", "two"], 2, [], 0))

    def test_native_claim_chunk_formula_uses_frozen_concurrency(self):
        for count, expected in ((1, 1000), (10, 1000), (11, 1100), (25, 2500)):
            with self.subTest(concurrency=count):
                dictionary = Mock()
                dictionary.claim_native_many.return_value = []
                fuzzer = make_fuzzer(NativeFuzzer, ExecutionConfig(concurrency=count), dictionary)
                fuzzer.set_base_path("base/")
                with patch.dict(options, {}, clear=True):
                    self.assertEqual(fuzzer._next_chunk(), [])
                dictionary.claim_native_many.assert_called_once_with(expected, "base/")


class TestAsyncExecutionConfig(IsolatedAsyncioTestCase):
    async def test_all_calibration_profiles_receive_each_engines_delay(self):
        for engine in (Fuzzer, AsyncFuzzer, NativeFuzzer):
            for delay in (0, 0.125):
                with self.subTest(engine=engine.__name__, delay=delay):
                    fuzzer = engine(
                        SimpleNamespace(backend=None), None,
                        filter_config=FilterConfig(exclude_response="custom"),
                        discovery_config=DiscoveryConfig(
                            prefixes=("pre-",), suffixes=("-end",), extensions=("html",),
                        ),
                        execution_config=ExecutionConfig(delay=delay),
                        match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
                    )
                    factory = AsyncMock() if engine is AsyncFuzzer else Mock()
                    factory_path = (
                        "lib.core.fuzzer.AsyncScanner.create"
                        if engine is AsyncFuzzer else "lib.core.fuzzer.Scanner"
                    )
                    with patch.dict(options, {}, clear=True), patch(factory_path, factory):
                        if engine is AsyncFuzzer:
                            await fuzzer.setup_scanners()
                        else:
                            fuzzer.setup_scanners()
                    self.assertGreater(len(factory.call_args_list), 4)
                    for call in factory.call_args_list:
                        self.assertEqual(call.kwargs["delay"], delay)

    async def test_async_workers_and_delay_ignore_global_options(self):
        for concurrency, delay, expected_workers in ((1, 0, 1), (3, 0.25, 3), (8, 0, 4)):
            with self.subTest(concurrency=concurrency, delay=delay):
                dictionary = make_dictionary(["one", "two", "three", "four"])
                fuzzer = make_fuzzer(
                    AsyncFuzzer, ExecutionConfig(concurrency=concurrency, delay=delay), dictionary,
                )
                fuzzer.setup_scanners = AsyncMock()
                fuzzer.scan = AsyncMock()
                original_worker = fuzzer.task_proc
                worker = AsyncMock(side_effect=original_worker)
                fuzzer.task_proc = worker
                with (
                    patch.dict(options, {}, clear=True),
                    patch("lib.core.fuzzer.asyncio.sleep", new_callable=AsyncMock) as sleep,
                ):
                    await asyncio.wait_for(fuzzer.start(), timeout=2)
                self.assertEqual(worker.await_count, expected_workers)
                self.assertEqual(fuzzer.scan.await_count, 4)
                self.assertEqual([call.args[0] for call in sleep.await_args_list], [delay] * 4)
                self.assertEqual(dictionary.__getstate__(), (["one", "two", "three", "four"], 4, [], 0))
                self.assertFalse(fuzzer._background_tasks)

    async def test_async_worker_bound_is_independent_for_simultaneous_fuzzers(self):
        release = asyncio.Event()
        ready = [asyncio.Event(), asyncio.Event()]
        active = [0, 0]
        peak = [0, 0]
        fuzzers = []

        for index, concurrency in enumerate((1, 3)):
            fuzzer = make_fuzzer(
                AsyncFuzzer, ExecutionConfig(concurrency=concurrency),
                make_dictionary(["one", "two", "three", "four"]),
            )
            fuzzer.setup_scanners = AsyncMock()

            async def scan(_path, index=index, concurrency=concurrency):
                active[index] += 1
                peak[index] = max(peak[index], active[index])
                if active[index] == concurrency:
                    ready[index].set()
                try:
                    await release.wait()
                finally:
                    active[index] -= 1

            fuzzer.scan = scan
            fuzzers.append(fuzzer)

        with patch.dict(options, {}, clear=True):
            tasks = [asyncio.create_task(fuzzer.start()) for fuzzer in fuzzers]
            try:
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready)), timeout=2)
                self.assertEqual(peak, [1, 3])
            finally:
                release.set()
                for task in tasks:
                    task.cancel()
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2)
        self.assertEqual(active, [0, 0])
        self.assertTrue(all(task.done() for task in tasks))
        self.assertTrue(all(not fuzzer._background_tasks for fuzzer in fuzzers))
