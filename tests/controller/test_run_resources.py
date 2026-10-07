"""Live handles have one owner; failures must not skip later cleanup phases."""

import asyncio
from unittest import TestCase
from unittest.mock import AsyncMock, Mock

from lib.controller.run_resources import RunResources


class TestRunResources(TestCase):
    def resources(self, events, failures=()):
        def action(name):
            def close():
                events.append(name)
                if name in failures:
                    raise RuntimeError(name)
            return close

        return RunResources(
            interface=Mock(close=action("terminal")),
            logger=Mock(close=action("logger")),
            reporter=Mock(finish=action("reporter")),
            requester=Mock(close=action("requester")),
            response_stores=(Mock(close=action("store")),),
        )

    def test_close_preserves_order_and_only_attempts_teardown_once(self):
        events = []
        resources = self.resources(events)
        resources.close()
        resources.close()
        self.assertEqual(events, ["reporter", "requester", "store", "terminal", "logger"])

    def test_each_failure_still_attempts_later_phases_without_retries(self):
        phases = ["reporter", "requester", "store", "terminal", "logger"]
        for phase in phases:
            with self.subTest(phase=phase):
                events = []
                resources = self.resources(events, failures=(phase,))
                with self.assertRaisesRegex(RuntimeError, phase):
                    resources.close()
                resources.close()
                self.assertEqual(events, phases)

    def test_multiple_failures_preserve_python_exception_chaining(self):
        events = []
        resources = self.resources(events, failures=("reporter", "requester", "terminal"))
        with self.assertRaisesRegex(RuntimeError, "terminal") as caught:
            resources.close()
        self.assertEqual(str(caught.exception.__context__), "requester")
        self.assertEqual(str(caught.exception.__context__.__context__), "reporter")
        self.assertEqual(events, ["reporter", "requester", "store", "terminal", "logger"])

    def test_early_report_finish_is_not_repeated_by_final_cleanup(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                events = []
                resources = self.resources(events, failures=("reporter",) if fails else ())
                if fails:
                    with self.assertRaisesRegex(RuntimeError, "reporter"):
                        resources.finish_reports()
                else:
                    resources.finish_reports()
                resources.finish_reports()
                resources.close()
                self.assertEqual(events, ["reporter", "requester", "store", "terminal", "logger"])

    def test_partial_preparation_closes_bootstrap_handles_and_optional_loop(self):
        for with_loop in (False, True):
            with self.subTest(with_loop=with_loop):
                events = []
                resources = RunResources(
                    interface=Mock(close=lambda: events.append("terminal")),
                    logger=Mock(close=lambda: events.append("logger")),
                    loop=Mock(close=lambda: events.append("loop")) if with_loop else None,
                )
                resources.close()
                self.assertEqual(events, (["loop"] if with_loop else []) + ["terminal", "logger"])

    def test_missing_reporter_does_not_mark_a_later_reporter_finished(self):
        resources = RunResources(interface=Mock(), logger=Mock())
        resources.finish_reports()
        reporter = resources.reporter = Mock()
        resources.close()
        reporter.finish.assert_called_once_with()

    def test_async_requester_is_awaited_before_loop_stores_and_diagnostics_close(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                events = []
                resources = self.resources(events)
                loop = asyncio.new_event_loop()
                self.addCleanup(loop.close)
                resources.loop = loop

                async def close_requester():
                    events.append("requester-start")
                    await asyncio.sleep(0)
                    self.assertFalse(loop.is_closed())
                    events.append("requester-finished")
                    if fails:
                        raise RuntimeError("requester")

                def close_store():
                    self.assertTrue(loop.is_closed())
                    events.append("store")

                resources.requester = Mock(close=AsyncMock(side_effect=close_requester))
                resources.response_stores = (Mock(close=close_store),)
                if fails:
                    with self.assertRaisesRegex(RuntimeError, "requester"):
                        resources.close()
                else:
                    resources.close()
                resources.requester.close.assert_awaited_once_with()
                self.assertTrue(loop.is_closed())
                self.assertEqual(events, [
                    "reporter", "requester-start", "requester-finished", "store", "terminal", "logger",
                ])

    def test_loop_close_failure_still_closes_stores_terminal_and_logger(self):
        events = []
        resources = self.resources(events)
        resources.requester = None
        resources.loop = Mock(close=Mock(side_effect=RuntimeError("loop")))
        with self.assertRaisesRegex(RuntimeError, "loop"):
            resources.close()
        resources.loop.close.assert_called_once_with()
        self.assertEqual(events, ["reporter", "store", "terminal", "logger"])

    def test_cancelled_async_close_still_closes_loop_and_downstream_handles(self):
        events = []
        resources = self.resources(events)
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        resources.loop = loop
        resources.requester = Mock(close=AsyncMock(side_effect=asyncio.CancelledError()))
        with self.assertRaises(asyncio.CancelledError):
            resources.close()
        resources.requester.close.assert_awaited_once_with()
        self.assertTrue(loop.is_closed())
        self.assertEqual(events, ["reporter", "store", "terminal", "logger"])

    def test_store_os_error_keeps_diagnostics_available_and_closes_next_store(self):
        events = []
        resources = self.resources(events)
        error = OSError("disk failure")
        failing = Mock(close=Mock(side_effect=error), destination="evidence.jsonl")
        failing.name = "JSONL"
        following = resources.response_stores[0]
        resources.response_stores = (failing, following)
        resources.interface.error.side_effect = lambda _: events.append("store-error")
        resources.close()
        resources.logger.exception.assert_called_once_with(error)
        resources.interface.error.assert_called_once_with(
            "Couldn't close JSONL response store at evidence.jsonl: disk failure"
        )
        self.assertEqual(events, ["reporter", "requester", "store-error", "store", "terminal", "logger"])

    def test_replacements_are_owned_even_when_bootstrap_close_fails(self):
        for fails in (False, True):
            for kind in ("terminal", "logger"):
                with self.subTest(kind=kind, fails=fails):
                    resources = RunResources(interface=Mock(), logger=Mock())
                    previous = resources.interface if kind == "terminal" else resources.logger
                    replacement = Mock()

                    def close_previous():
                        owned = resources.interface if kind == "terminal" else resources.logger
                        self.assertIs(owned, replacement)
                        if fails:
                            raise RuntimeError("bootstrap")

                    previous.close.side_effect = close_previous
                    replace = resources.replace_terminal if kind == "terminal" else resources.replace_logger
                    if fails:
                        with self.assertRaisesRegex(RuntimeError, "bootstrap"):
                            replace(replacement)
                    else:
                        replace(replacement)
                    resources.close()
                    previous.close.assert_called_once_with()
                    replacement.close.assert_called_once_with()

    def test_owners_do_not_share_handles_or_completion_flags(self):
        first_events, second_events = [], []
        first, second = self.resources(first_events), self.resources(second_events)
        first.finish_reports()
        first.close()
        self.assertEqual(second_events, [])
        second.close()
        self.assertEqual(first_events, second_events)

    def test_live_handles_are_not_exposed_by_repr(self):
        resources = RunResources(interface=Mock(name="private-output"), logger=Mock(name="private-log"))
        self.assertNotIn("private", repr(resources))
