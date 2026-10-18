"""Execution does not take ownership of the embedding process's globals."""

import asyncio
import signal
import threading
from contextlib import contextmanager
from io import StringIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.controller.controller import Controller
from lib.core.option_defaults import default_options
from lib.controller.event_loop import create_event_loop
from lib.utils.cli import cli_interrupts


class TestProcessIsolation(TestCase):
    def values(self, backend="python", async_mode=False):
        values = default_options()
        values.update(
            urls=[], wordlists=[], wordlist_backend="python", output_formats=[],
            request_backend=backend, async_mode=async_mode, color=False, quiet=True,
        )
        return values

    def test_unmanaged_controller_preserves_signal_handlers_for_every_engine(self):
        previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        for backend, async_mode, requester_path in (
            ("python", False, "lib.connection.requester.Requester"),
            ("python", True, "lib.connection.requester.AsyncRequester"),
            ("native", False, "lib.connection.native.NativeRequester"),
        ):
            with self.subTest(backend=backend, async_mode=async_mode):
                requester = Mock(close=AsyncMock()) if async_mode else Mock()
                controller = Controller(self.values(backend, async_mode), output=StringIO())
                try:
                    with patch(requester_path, return_value=requester):
                        controller.run()
                    for number, handler in previous.items():
                        self.assertIs(signal.getsignal(number), handler)
                    requester.close.assert_called_once_with()
                    if async_mode:
                        requester.close.assert_awaited_once_with()
                        self.assertTrue(controller.resources.loop.is_closed())
                finally:
                    # Keep the red-phase reproduction from leaking handlers.
                    for number, handler in previous.items():
                        signal.signal(number, handler)

    def test_uvloop_creation_does_not_replace_the_process_policy(self):
        loop_factory = Mock(side_effect=asyncio.new_event_loop)
        optional_uvloop = SimpleNamespace(
            new_event_loop=loop_factory, EventLoopPolicy=Mock(),
        )
        requester = Mock(close=AsyncMock())
        with (
            patch.dict("sys.modules", {"uvloop": optional_uvloop}),
            patch("asyncio.set_event_loop_policy") as set_policy,
            patch("lib.connection.requester.AsyncRequester", return_value=requester),
        ):
            controller = Controller(self.values(async_mode=True), output=StringIO())
            controller.run()
        set_policy.assert_not_called()
        loop_factory.assert_called_once_with()
        optional_uvloop.EventLoopPolicy.assert_not_called()
        self.assertTrue(controller.resources.loop.is_closed())

    def test_async_loop_falls_back_only_when_optional_import_is_unavailable(self):
        with (
            patch.dict("sys.modules", {"uvloop": None}),
            patch("asyncio.set_event_loop_policy") as set_policy,
            patch("asyncio.set_event_loop") as set_current,
        ):
            loop = create_event_loop()
            try:
                self.assertIsInstance(loop, asyncio.AbstractEventLoop)
                self.assertFalse(loop.is_closed())
            finally:
                loop.close()
        set_policy.assert_not_called()
        set_current.assert_not_called()

    def test_uvloop_factory_failure_propagates_without_silent_fallback(self):
        optional_uvloop = SimpleNamespace(new_event_loop=Mock(side_effect=RuntimeError("loop failed")))
        with (
            patch.dict("sys.modules", {"uvloop": optional_uvloop}),
            patch("asyncio.new_event_loop") as fallback,
            self.assertRaisesRegex(RuntimeError, "loop failed"),
        ):
            create_event_loop()
        fallback.assert_not_called()

    def test_unmanaged_execution_can_run_in_a_worker_without_process_patching(self):
        for backend, async_mode in (("python", False), ("python", True), ("native", False)):
            with self.subTest(backend=backend, async_mode=async_mode):
                controller = Controller(self.values(backend, async_mode), output=StringIO())
                errors = []

                def worker():
                    try:
                        controller.run()
                    except BaseException as error:
                        errors.append(error)

                # No targets: real requester/loop acquisition and teardown,
                # but no network access. Native availability is tested elsewhere.
                with patch("lib.connection.native.NativeRequester", return_value=Mock()):
                    thread = threading.Thread(target=worker)
                    thread.start()
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertTrue(controller.resources.interface._output_buffer.closed)

    def test_signal_scope_surrounds_execution_and_restores_before_cleanup(self):
        for backend, async_mode, requester_path in (
            ("python", False, "lib.connection.requester.Requester"),
            ("python", True, "lib.connection.requester.AsyncRequester"),
            ("native", False, "lib.connection.native.NativeRequester"),
        ):
            for failure in (None, "execution", "reports", "requester"):
                with self.subTest(backend=backend, async_mode=async_mode, failure=failure):
                    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
                    callback = Mock()
                    values = self.values(backend, async_mode)
                    values["urls"] = ["http://example.test/"]
                    controller = Controller(values, output=StringIO())
                    events = []

                    def close():
                        for number, handler in previous.items():
                            self.assertIs(signal.getsignal(number), handler)
                        events.append("close")
                        if failure == "requester":
                            raise RuntimeError("requester failed")

                    requester = Mock(close=AsyncMock(side_effect=close) if async_mode else Mock(side_effect=close))

                    def set_target(url):
                        controller.target_progress.url = url
                        controller.target_progress.base_path = ""

                    def execute():
                        for number in previous:
                            signal.getsignal(number)(number, None)
                        if failure == "execution":
                            raise RuntimeError("execution failed")

                    with (
                        patch(requester_path, return_value=requester),
                        patch.object(controller, "set_target", side_effect=set_target),
                        patch.object(controller, "start", side_effect=execute),
                        patch("lib.report.manager.ReportManager.finish", side_effect=RuntimeError("reports failed") if failure == "reports" else None),
                    ):
                        if failure:
                            with self.assertRaisesRegex(RuntimeError, failure + " failed"):
                                controller.run(interrupts=cli_interrupts(callback))
                        else:
                            controller.run(interrupts=cli_interrupts(callback))
                    self.assertEqual(callback.call_count, 2)
                    self.assertEqual(events, ["close"])
                    for number, handler in previous.items():
                        self.assertIs(signal.getsignal(number), handler)
                    self.assertTrue(controller.resources.interface._output_buffer.closed)
                    if async_mode:
                        self.assertTrue(controller.resources.loop.is_closed())

    def test_failed_preparation_never_enters_cli_scope(self):
        for phase in ("_prepare", "requester", "loop"):
            with self.subTest(phase=phase):
                entered = []

                @contextmanager
                def interrupts():
                    entered.append(True)
                    yield

                controller = Controller(self.values(async_mode=True), output=StringIO())
                target = {
                    "_prepare": "lib.controller.controller.Controller._prepare",
                    "requester": "lib.connection.requester.AsyncRequester",
                    "loop": "lib.controller.controller.create_event_loop",
                }[phase]
                with patch(target, side_effect=RuntimeError("preparation failed")):
                    with self.assertRaisesRegex(RuntimeError, "preparation failed"):
                        controller.run(interrupts=interrupts())
                self.assertEqual(entered, [])
                self.assertTrue(controller.resources.interface._output_buffer.closed)

    def test_loop_creation_failure_cannot_leave_an_unclosable_async_requester(self):
        controller = Controller(self.values(async_mode=True), output=StringIO())
        with (
            patch("lib.controller.controller.create_event_loop", side_effect=RuntimeError("loop failed")),
            patch("lib.connection.requester.AsyncRequester") as requester,
            self.assertRaisesRegex(RuntimeError, "loop failed"),
        ):
            controller.run()
        requester.assert_not_called()
        self.assertIsNone(controller.resources.requester)

    def test_requester_creation_failure_closes_the_owned_loop(self):
        controller = Controller(self.values(async_mode=True), output=StringIO())
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        with (
            patch("lib.controller.controller.create_event_loop", return_value=loop),
            patch("lib.connection.requester.AsyncRequester", side_effect=RuntimeError("requester failed")),
            self.assertRaisesRegex(RuntimeError, "requester failed"),
        ):
            controller.run()
        self.assertTrue(loop.is_closed())
