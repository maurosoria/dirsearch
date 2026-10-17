import asyncio
import gc
import weakref
from unittest import IsolatedAsyncioTestCase

from lib.connection.response import NativeResponse
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig
from lib.core.filter_config import FilterConfig
from lib.core.fuzzer import AsyncFuzzer, Fuzzer, NativeFuzzer
from lib.core.scanner import AsyncScanner, BaseScanner, Scanner
from lib.core.settings import WILDCARD_TEST_POINT_MARKER
from lib.utils.random import StealthWordGenerator


class RecordingRequester:
    # NativeFuzzer uses synchronous requests for calibration, before scan_chunks.
    backend = None

    def __init__(self):
        self.paths = []

    def request(self, path):
        self.paths.append(path)
        return NativeResponse(
            f"https://example.com/{path}", 200,
            [("content-type", "text/plain")], b"a fixed missing page",
        )


class AsyncRecordingRequester(RecordingRequester):
    async def request(self, path):
        await asyncio.sleep(0)
        return super().request(path)


class TestCalibrationWords(IsolatedAsyncioTestCase):
    def make_fuzzer(self, engine, requester):
        return engine(
            requester, None, filter_config=FilterConfig(
                auto_calibration=True, exclude_response="known-missing",
            ),
            discovery_config=DiscoveryConfig(
                prefixes=("private-",), suffixes=(".bak",), extensions=("php",),
            ),
            execution_config=ExecutionConfig(),
            match_callbacks=(), not_found_callbacks=(), error_callbacks=(),
        )

    def test_standalone_scanners_have_independent_generators(self):
        scanners = [
            BaseScanner(None, filter_config=FilterConfig(), delay=0)
            for _ in range(2)
        ]
        self.assertIsNot(scanners[0].word_generator, scanners[1].word_generator)
        self.assertIsNot(scanners[0].word_generator._rng, scanners[1].word_generator._rng)
        self.assertIsNot(scanners[0].word_generator._seen, scanners[1].word_generator._seen)

    def test_fuzzers_have_independent_generators_in_every_engine(self):
        fuzzers = [
            self.make_fuzzer(engine, RecordingRequester())
            for engine in (Fuzzer, AsyncFuzzer, NativeFuzzer)
            for _ in range(2)
        ]
        generators = [fuzzer._word_generator for fuzzer in fuzzers]
        self.assertEqual(len({id(generator) for generator in generators}), 6)
        first_word = generators[0].generate()
        for generator in generators[1:]:
            self.assertNotIn(first_word, generator._seen)

    async def test_injected_generator_drives_initial_and_extra_samples(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                generator = StealthWordGenerator(seed=73)
                expected = StealthWordGenerator(seed=73)
                requester = AsyncRecordingRequester() if asynchronous else RecordingRequester()
                for template in ("root/{}", "root/.{}.php"):
                    kwargs = dict(
                        filter_config=FilterConfig(auto_calibration=True), delay=0,
                        path=template.format(WILDCARD_TEST_POINT_MARKER),
                        word_generator=generator,
                    )
                    if asynchronous:
                        scanner = await AsyncScanner.create(requester, **kwargs)
                    else:
                        scanner = Scanner(requester, **kwargs)
                    self.assertIs(scanner.word_generator, generator)
                    self.assertEqual(scanner.sample_count, 4)
                    self.assertEqual(
                        requester.paths[-4:],
                        [template.format(expected.generate()) for _ in range(4)],
                    )

    async def test_every_profile_and_directory_borrows_the_fuzzer_generator(self):
        for engine in (Fuzzer, AsyncFuzzer, NativeFuzzer):
            with self.subTest(engine=engine.__name__):
                requester = AsyncRecordingRequester() if engine is AsyncFuzzer else RecordingRequester()
                fuzzer = self.make_fuzzer(engine, requester)
                generator = StealthWordGenerator(seed=74)
                fuzzer._word_generator = generator
                expected = StealthWordGenerator(seed=74)
                for directory in ("", "nested/"):
                    fuzzer.set_base_path(directory)
                    start = len(requester.paths)
                    if engine is AsyncFuzzer:
                        await fuzzer.setup_scanners()
                    else:
                        fuzzer.setup_scanners()
                    profiles = fuzzer.filter_state.scanners
                    self.assertIn("custom", profiles["default"])
                    self.assertIn("private-", profiles["prefixes"])
                    self.assertIn(".bak", profiles["suffixes"])
                    self.assertIn(".php", profiles["suffixes"])
                    for category in profiles.values():
                        for scanner in category.values():
                            self.assertIs(scanner.word_generator, generator)
                    paths = requester.paths[start:]
                    self.assertGreater(len(paths), 4)
                    for path in paths:
                        word = expected.generate()
                        if path != "known-missing":
                            self.assertTrue(path.startswith(directory))
                            self.assertIn(word, path)
                self.assertEqual(len(generator._seen), len(requester.paths))

    async def test_interleaved_async_scanners_do_not_consume_each_others_words(self):
        requesters = [AsyncRecordingRequester(), AsyncRecordingRequester()]
        scanners = await asyncio.gather(*(
            AsyncScanner.create(
                requester, filter_config=FilterConfig(auto_calibration=True),
                delay=0, path=WILDCARD_TEST_POINT_MARKER,
                word_generator=StealthWordGenerator(seed=75),
            )
            for requester in requesters
        ))
        expected = StealthWordGenerator(seed=75)
        self.assertEqual(requesters[0].paths, [expected.generate() for _ in range(4)])
        self.assertEqual(requesters[0].paths, requesters[1].paths)
        self.assertIsNot(scanners[0].word_generator, scanners[1].word_generator)

    def test_generator_history_is_collectable_with_its_fuzzer_and_profiles(self):
        fuzzer = self.make_fuzzer(Fuzzer, RecordingRequester())
        fuzzer.setup_scanners()
        generator_ref = weakref.ref(fuzzer._word_generator)
        self.assertTrue(generator_ref()._seen)
        del fuzzer
        # Profiles refer to their shared profile dictionary; collect that cycle
        # and prove no process-wide generator retains its accumulated history.
        gc.collect()
        self.assertIsNone(generator_ref())
