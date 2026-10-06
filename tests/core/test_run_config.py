"""The composition aggregate is immutable data, not an owner of resources."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from unittest import TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.core.discovery_config import DiscoveryConfig
from lib.core.execution_config import ExecutionConfig, ScanEngine
from lib.core.filter_config import FilterConfig
from lib.core.log_config import LogConfig
from lib.core.report_config import ReportConfig
from lib.core.request_config import RequestConfig
from lib.core.result_config import ResultConfig
from lib.core.run_config import RunConfig
from lib.core.target_config import TargetConfig
from lib.core.terminal_config import TerminalConfig
from lib.core.wordlist_config import WordlistConfig


class TestRunConfig(TestCase):
    def values(self, **changes):
        values = deepcopy(options)
        values.update(changes)
        return values

    def test_every_policy_uses_supplied_normalized_values_without_globals(self):
        values = self.values(
            headers={"Authorization": "Bearer private-value"},
            extensions=["html"], prefixes=["pre-"], output_formats=["json"],
            thread_count=3, delay=0.125, include_status_codes={200},
            log_file="test.log", scheme="https", full_url=True,
        )
        with patch.dict(options, {}, clear=True):
            config = RunConfig.from_options(values)
            self.assertEqual(config, RunConfig(
                wordlist=WordlistConfig.from_options(values),
                request=RequestConfig.from_options(values),
                filters=FilterConfig.from_options(values),
                discovery=DiscoveryConfig.from_options(values),
                execution=ExecutionConfig.from_options(values),
                reports=ReportConfig.from_options(values),
                target=TargetConfig.from_options(values),
                terminal=TerminalConfig.from_options(values),
                logging=LogConfig.from_options(values),
                results=ResultConfig.from_options(values),
            ))

    def test_shared_settings_agree_for_every_engine_and_capture_destination(self):
        for engine in ScanEngine:
            for directory, jsonl in ((None, None), ("responses", None), (None, "responses.jsonl")):
                with self.subTest(engine=engine, directory=directory, jsonl=jsonl):
                    config = RunConfig.from_options(self.values(
                        request_backend="native" if engine is ScanEngine.NATIVE else "python",
                        async_mode=engine is ScanEngine.ASYNC,
                        save_response=directory, save_response_jsonl=jsonl,
                        thread_count=3, delay=0.125,
                    ))
                    self.assertIs(config.execution.engine, engine)
                    self.assertEqual(config.request.concurrency, config.execution.concurrency)
                    self.assertEqual(config.terminal.concurrency, config.execution.concurrency)
                    self.assertEqual(config.request.delay, config.execution.delay)
                    self.assertIs(config.request.capture_full_body, bool(directory or jsonl))
                    self.assertIs(config.request.capture_full_body, config.results.capture_full_body)
                    self.assertIs(config.wordlist.native_corpus, engine is ScanEngine.NATIVE)

    def test_nested_inputs_are_detached_and_both_levels_are_frozen(self):
        values = self.values(
            headers={"X-Source": "prepared"}, extensions=["html"],
            prefixes=["pre-"], proxies=["http://proxy.test/"],
            include_status_codes={200}, skip_on_status={429},
            match_sizes=[[3, 9]], output_formats=["json"],
            data=bytearray(b"prepared"),
        )
        config = RunConfig.from_options(values)
        values["headers"].clear()
        values["extensions"].clear()
        values["prefixes"].clear()
        values["proxies"].clear()
        values["include_status_codes"].clear()
        values["skip_on_status"].clear()
        values["match_sizes"][0][0] = 999
        values["output_formats"].clear()
        values["data"].clear()
        self.assertEqual(config.request.headers, (("X-Source", "prepared"),))
        self.assertEqual(config.request.body, b"prepared")
        self.assertEqual(config.request.proxies, ("http://proxy.test/",))
        self.assertEqual(config.wordlist.extensions, ("html",))
        self.assertEqual(config.discovery.prefixes, ("pre-",))
        self.assertEqual(config.terminal.prefixes, ("pre-",))
        self.assertEqual(config.filters.include_status_codes, {200})
        self.assertEqual(config.filters.match_sizes, ((3, 9),))
        self.assertEqual(config.execution.skip_on_status, {429})
        self.assertEqual(config.reports.formats, ("json",))
        with self.assertRaises(FrozenInstanceError):
            config.request = RequestConfig()
        with self.assertRaises(FrozenInstanceError):
            config.execution.concurrency = 99

    def test_invalid_engine_fails_before_other_policy_adapters(self):
        # Deliberately incomplete: engine validation must precede other lookups.
        for backend, async_mode in (("invalid", False), ("native", True)):
            with (
                self.subTest(backend=backend),
                patch.object(RequestConfig, "from_options") as request,
                self.assertRaises(ValueError),
            ):
                RunConfig.from_options({"request_backend": backend, "async_mode": async_mode})
            request.assert_not_called()

    def test_blacklist_attachment_preserves_every_other_policy_identity(self):
        original = RunConfig()
        source = {403: ["private/"]}
        attached = original.with_blacklists(source)
        source[403].clear()
        self.assertEqual(dict(original.filters.blacklists), {})
        self.assertEqual(dict(attached.filters.blacklists), {403: ("private/",)})
        with self.assertRaises(TypeError):
            attached.filters.blacklists[404] = ()
        for old, new in (
            (original.wordlist, attached.wordlist), (original.request, attached.request),
            (original.discovery, attached.discovery), (original.execution, attached.execution),
            (original.reports, attached.reports), (original.target, attached.target),
            (original.terminal, attached.terminal), (original.logging, attached.logging),
            (original.results, attached.results),
        ):
            self.assertIs(old, new)
        replaced = attached.with_blacklists({404: ["missing/"]})
        self.assertEqual(dict(replaced.filters.blacklists), {404: ("missing/",)})
        self.assertEqual(dict(attached.filters.blacklists), {403: ("private/",)})

    def test_aggregate_repr_omits_secret_bearing_policies(self):
        config = RunConfig.from_options(self.values(
            auth="user:private-value", headers={"Authorization": "Bearer private-value"},
            data="private-body", match_regex="private-pattern",
            mysql_url="mysql://user:private-value@db.test/database",
        ))
        self.assertEqual(repr(config), "RunConfig()")

    def test_default_aggregates_do_not_share_policy_instances(self):
        first, second = RunConfig(), RunConfig()
        self.assertEqual(first, second)
        self.assertIsNot(first.request, second.request)
        self.assertIsNot(first.filters, second.filters)
        self.assertIsNot(first.filters.blacklists, second.filters.blacklists)
