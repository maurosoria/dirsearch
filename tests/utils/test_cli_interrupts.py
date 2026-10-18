import signal
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.utils.cli import cli_interrupts


class TestCLIInterrupts(TestCase):
    def setUp(self):
        self.previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        for number, handler in self.previous.items():
            self.addCleanup(signal.signal, number, handler)

    def assert_restored(self):
        for number, handler in self.previous.items():
            self.assertIs(signal.getsignal(number), handler)

    def test_lazy_scope_routes_both_signals_and_restores_handlers(self):
        callback = Mock()
        scope = cli_interrupts(callback)
        self.assert_restored()
        with scope:
            for number in self.previous:
                signal.getsignal(number)(number, None)
        self.assertEqual(callback.call_count, 2)
        self.assert_restored()

    def test_every_exception_path_restores_handlers(self):
        for error in (RuntimeError("scan failed"), KeyboardInterrupt(), SystemExit(2)):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)) as raised:
                    with cli_interrupts(Mock()):
                        raise error
                self.assertIs(raised.exception, error)
                self.assert_restored()

    def test_nested_scopes_restore_the_previous_owner_in_order(self):
        outer, inner = Mock(), Mock()
        with cli_interrupts(outer):
            outer_handler = signal.getsignal(signal.SIGINT)
            with cli_interrupts(inner):
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
            self.assertIs(signal.getsignal(signal.SIGINT), outer_handler)
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        outer.assert_called_once_with()
        inner.assert_called_once_with()
        self.assert_restored()

    def test_partial_registration_failure_rolls_back_installed_handler(self):
        register = signal.signal

        def fail_second(number, handler):
            if number == signal.SIGTERM:
                raise OSError("registration failed")
            return register(number, handler)

        with patch("lib.utils.cli.signal.signal", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "registration failed"):
                with cli_interrupts(Mock()):
                    self.fail("execution must not start after failed registration")
        self.assert_restored()

    def test_failed_restoration_still_attempts_other_handler(self):
        register = signal.signal

        def fail_restore(number, handler):
            if number == signal.SIGTERM and handler is self.previous[number]:
                raise OSError("restoration failed")
            return register(number, handler)

        with patch("lib.utils.cli.signal.signal", side_effect=fail_restore):
            with self.assertRaisesRegex(OSError, "restoration failed"):
                with cli_interrupts(Mock()):
                    pass
        self.assertIs(signal.getsignal(signal.SIGINT), self.previous[signal.SIGINT])

    def test_cli_scope_rejects_worker_thread_without_changing_handlers(self):
        errors = []

        def worker():
            try:
                with cli_interrupts(Mock()):
                    self.fail("CLI signals require the main thread")
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assert_restored()
