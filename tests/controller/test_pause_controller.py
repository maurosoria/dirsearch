import signal
import subprocess
import sys
from unittest import skipUnless, TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.dictionary import Dictionary
from lib.core.exceptions import QuitInterrupt, SkipTargetInterrupt


def make_dictionary(items=()) -> Dictionary:
    dictionary = object.__new__(Dictionary)
    dictionary.__setstate__((list(items), 0, [], 0))
    return dictionary


class SignalItems(list):
    def __init__(self, items, callback):
        super().__init__(items)
        self._callback = callback
        self._called = False

    def __len__(self):
        if not self._called:
            self._called = True
            self._callback(signal.SIGINT, None)
        return super().__len__()


class TestPauseController(TestCase):
    def make_controller(self):
        controller = object.__new__(Controller)
        controller._handling_pause = False
        controller._pause_requested = False
        controller._force_quit_handler = Mock()
        return controller

    def test_signal_handler_only_records_pause_request(self):
        controller = self.make_controller()

        controller.request_pause(signal.SIGINT, None)

        self.assertTrue(controller._pause_requested)
        controller._force_quit_handler.on_pause_start.assert_called_once_with()
        controller._force_quit_handler.check_force_quit.assert_not_called()

    def test_signal_during_dictionary_claim_returns_without_reentrant_lock(self):
        controller = self.make_controller()
        dictionary = make_dictionary(["admin"])
        dictionary._items = SignalItems(dictionary._items, controller.request_pause)

        path = dictionary.claim_next()

        self.assertEqual(path, "admin")
        self.assertTrue(controller._pause_requested)
        self.assertEqual(dictionary.__getstate__()[1], 1)

    def test_repeated_signal_uses_force_quit_policy(self):
        controller = self.make_controller()
        controller._pause_requested = True

        controller.request_pause(signal.SIGINT, None)

        controller._force_quit_handler.check_force_quit.assert_called_once_with()

    def test_pause_continue_resets_signal_state_and_resumes_workers(self):
        controller = self.make_controller()
        controller._pause_requested = True
        controller.directories = [""]
        controller.fuzzer = Mock()
        controller.fuzzer.pause.return_value = True

        with (
            patch.dict(options, {"urls": ["https://example.com"], "async_mode": False}),
            patch("builtins.input", return_value="c"),
            patch("lib.controller.controller.interface"),
        ):
            controller.handle_pause()

        self.assertFalse(controller._pause_requested)
        self.assertFalse(controller._handling_pause)
        controller._force_quit_handler.on_resume.assert_called_once_with()
        controller.fuzzer.play.assert_called_once_with()

    def test_next_directory_clears_pause_before_stopping_workers(self):
        controller = self.make_controller()
        controller._pause_requested = True
        controller.directories = ["first", "second"]
        controller.fuzzer = Mock()
        controller.fuzzer.pause.return_value = True
        controller.fuzzer.wait.return_value = True

        with (
            patch.dict(options, {"urls": ["https://example.com"], "async_mode": False}),
            patch("builtins.input", return_value="n"),
            patch("lib.controller.controller.interface"),
        ):
            controller.handle_pause()

        self.assertFalse(controller._pause_requested)
        self.assertFalse(controller._handling_pause)
        controller.fuzzer.quit.assert_called_once_with()
        controller.fuzzer.wait.assert_called_once()

    def test_skip_target_clears_pause_before_raising(self):
        controller = self.make_controller()
        controller._pause_requested = True
        controller.directories = [""]
        controller.fuzzer = Mock()
        controller.fuzzer.pause.return_value = True
        controller.fuzzer.wait.return_value = True

        with (
            patch.dict(
                options,
                {
                    "urls": ["https://example.com", "https://example.net"],
                    "async_mode": False,
                },
            ),
            patch("builtins.input", return_value="s"),
            patch("lib.controller.controller.interface"),
            self.assertRaises(SkipTargetInterrupt),
        ):
            controller.handle_pause()

        self.assertFalse(controller._pause_requested)
        self.assertFalse(controller._handling_pause)

    def test_pause_save_runs_from_safe_point_before_worker_shutdown(self):
        controller = self.make_controller()
        controller._pause_requested = True
        controller.directories = [""]
        events = []
        controller.fuzzer = Mock()
        controller.fuzzer.pause.side_effect = lambda: events.append("pause") or True
        controller.fuzzer.quit.side_effect = lambda: events.append("quit")
        controller.fuzzer.wait.side_effect = lambda **_: events.append("wait") or True
        controller._export = Mock(side_effect=lambda _path: events.append("save"))

        with (
            patch.dict(
                options,
                {
                    "urls": ["https://example.com"],
                    "async_mode": False,
                    "session_file": None,
                },
            ),
            patch("builtins.input", side_effect=["q", "s", "session"]),
            patch("lib.controller.controller.interface"),
            self.assertRaises(QuitInterrupt),
        ):
            controller.handle_pause()

        self.assertEqual(events, ["pause", "save", "quit", "wait"])

    @skipUnless(hasattr(signal, "SIGUSR1"), "requires POSIX user signals")
    def test_real_signal_during_claim_and_session_save_does_not_deadlock(self):
        source = r'''
import signal
import tempfile
from unittest.mock import Mock
from lib.controller.controller import Controller
from lib.controller.session import SessionStore
from lib.core.dictionary import Dictionary

controller = object.__new__(Controller)
controller._handling_pause = False
controller._pause_requested = False
controller._force_quit_handler = Mock()
dictionary = object.__new__(Dictionary)
dictionary.__setstate__((["admin"], 0, [], 0))

class SignalItems(list):
    fired = False
    def __len__(self):
        if not self.fired:
            self.fired = True
            signal.raise_signal(signal.SIGUSR1)
        return super().__len__()

dictionary._items = SignalItems(dictionary._items)
signal.signal(signal.SIGUSR1, controller.request_pause)
assert dictionary.claim_next() == "admin"
assert controller._pause_requested
controller.dictionary = dictionary
controller.start_time = 0
controller.passed_urls = set()
controller.directories = [""]
controller.jobs_processed = 0
controller.errors = 0
controller.consecutive_errors = 0
controller.base_path = ""
controller.url = "https://example.com/"
controller.old_session = False
with tempfile.TemporaryDirectory() as directory:
    SessionStore({}).save(controller, directory, "")
    restored = SessionStore({}).load(directory)
assert restored["dictionary"]["extra"] == ["admin"]
print("signal-safe")
'''

        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=".",
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "signal-safe")
