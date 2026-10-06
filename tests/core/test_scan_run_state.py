import sys
from dataclasses import FrozenInstanceError
from unittest import TestCase

from lib.core.scan_run_state import ScanRunState
from lib.core.task_spec import TaskSpec


class TestScanRunState(TestCase):
    def test_preparing_targets_preserves_restored_run_progress(self):
        state = ScanRunState(["old"])
        state.activate_next()
        state.finish_active()
        state.passed_urls.add("http://first.test/current/")
        state.jobs_processed = 3
        state.errors = 5
        state.consecutive_errors = 2
        state.old_session = True
        targets = ["resumed", "pending", "pending"]
        state.prepare_targets(targets)
        targets.clear()
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["resumed", "pending", "pending"])
        self.assertEqual(state.pending_count, 3)
        self.assertIsNone(state.active_task)
        self.assertEqual(state.passed_urls, {"http://first.test/current/"})
        self.assertEqual((state.jobs_processed, state.errors, state.consecutive_errors), (3, 5, 2))
        self.assertTrue(state.old_session)

    def test_preparing_targets_rejects_active_work_without_consuming_input(self):
        state = ScanRunState(["active", "pending"])
        state.activate_next()

        def must_not_iterate():
            raise AssertionError("consumed input before checking active state")
            yield

        with self.assertRaisesRegex(RuntimeError, "target is active"):
            state.prepare_targets(must_not_iterate())
        self.assertEqual(state.active_task.target, "active")
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["active", "pending"])

    def test_failed_input_preparation_keeps_previous_queue_and_totals(self):
        state = ScanRunState(["finished", "pending"])
        state.activate_next()
        state.finish_active()
        state.jobs_processed = 3

        def broken_input():
            yield "replacement"
            raise ValueError("input failed")

        with self.assertRaisesRegex(ValueError, "input failed"):
            state.prepare_targets(broken_input())
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["pending"])
        self.assertEqual(state.jobs_processed, 3)

    def test_run_counters_and_scheduled_urls_are_not_shared(self):
        first = ScanRunState()
        second = ScanRunState()
        first.passed_urls.add("http://first.test/")
        first.jobs_processed = 4
        first.errors = 2
        first.consecutive_errors = 1
        first.old_session = True
        self.assertEqual(second.passed_urls, set())
        self.assertEqual((second.jobs_processed, second.errors, second.consecutive_errors), (0, 0, 0))
        self.assertFalse(second.old_session)

    def test_empty_run_has_no_active_or_pending_target(self):
        state = ScanRunState()
        self.assertIsNone(state.active_task)
        self.assertEqual(state.pending_count, 0)
        self.assertEqual([task.target for task in state.snapshot_tasks()], [])
        self.assertIsNone(state.activate_next())

    def test_activation_separates_active_from_pending(self):
        state = ScanRunState(["first", "second"])
        self.assertEqual(state.activate_next().target, "first")
        self.assertEqual(state.active_task.target, "first")
        self.assertEqual(state.pending_count, 1)
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["first", "second"])

        state.finish_active()
        self.assertIsNone(state.active_task)
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["second"])
        self.assertEqual(state.activate_next().target, "second")
        self.assertEqual(state.pending_count, 0)
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["second"])
        state.finish_active()
        self.assertIsNone(state.activate_next())
        self.assertEqual([task.target for task in state.snapshot_tasks()], [])

    def test_active_target_cannot_be_replaced_even_without_pending_work(self):
        for targets in (["first"], ["first", "second"]):
            with self.subTest(targets=targets):
                state = ScanRunState(targets)
                state.activate_next()
                with self.assertRaisesRegex(RuntimeError, "Finish the active target"):
                    state.activate_next()
                self.assertEqual(state.active_task.target, "first")
                self.assertEqual([task.target for task in state.snapshot_tasks()], targets)

    def test_finishing_without_an_active_target_is_an_error(self):
        state = ScanRunState(["first"])
        with self.assertRaisesRegex(RuntimeError, "no active target"):
            state.finish_active()
        state.activate_next()
        state.finish_active()
        with self.assertRaisesRegex(RuntimeError, "no active target"):
            state.finish_active()

    def test_input_and_snapshots_do_not_alias_state(self):
        targets = ["first", "second"]
        state = ScanRunState(targets)
        snapshot = state.snapshot_tasks()
        targets.clear()
        self.assertIsInstance(snapshot, tuple)
        self.assertIs(state.activate_next(), snapshot[0])
        with self.assertRaises(FrozenInstanceError):
            snapshot[0].target = "unrelated"
        state.finish_active()
        self.assertEqual(snapshot, (TaskSpec("first"), TaskSpec("second")))
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["second"])

    def test_duplicate_descriptors_keep_distinct_queue_positions(self):
        state = ScanRunState(["same", "same"])
        first, second = state.snapshot_tasks()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIs(state.activate_next(), first)
        state.finish_active()
        self.assertIs(state.activate_next(), second)
        self.assertEqual(state.pending_count, 0)
        self.assertEqual(state.snapshot_tasks(), (second,))

    def test_preparation_does_not_mutate_previously_captured_descriptors(self):
        state = ScanRunState(["first", "second"])
        snapshot = state.snapshot_tasks()
        state.prepare_targets(["replacement"])
        self.assertEqual(snapshot, (TaskSpec("first"), TaskSpec("second")))
        self.assertEqual(state.snapshot_tasks(), (TaskSpec("replacement"),))

    def test_order_duplicates_and_raw_url_text_are_preserved(self):
        targets = [
            "https://example.test/a%2Fb?next=/home",
            "http://[::1]:8080/",
            "https://example.test/café",
            "http://[::1]:8080/",
        ]
        state = ScanRunState(iter(targets))
        for index, target in enumerate(targets):
            self.assertEqual(state.activate_next().target, target)
            self.assertEqual([task.target for task in state.snapshot_tasks()], targets[index:])
            state.finish_active()
        self.assertIsNone(state.activate_next())

    def test_empty_target_is_not_the_exhaustion_sentinel(self):
        # URL validation belongs to the controller, not this state container.
        state = ScanRunState(["", "next"])
        self.assertEqual(state.activate_next().target, "")
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["", "next"])
        with self.assertRaises(RuntimeError):
            state.activate_next()
        state.finish_active()
        self.assertEqual(state.activate_next().target, "next")

    def test_runs_do_not_share_progress(self):
        targets = ["first", "second"]
        first = ScanRunState(targets)
        second = ScanRunState(targets)
        first.activate_next()
        first.finish_active()
        self.assertEqual([task.target for task in first.snapshot_tasks()], ["second"])
        self.assertIsNone(second.active_task)
        self.assertEqual([task.target for task in second.snapshot_tasks()], targets)
        self.assertEqual(targets, ["first", "second"])

    def test_checkpoint_reactivates_unfinished_target_before_pending_work(self):
        state = ScanRunState(["finished", "interrupted", "pending"])
        state.activate_next()
        state.finish_active()
        state.activate_next()

        resumed = ScanRunState([task.target for task in state.snapshot_tasks()])
        self.assertIsNone(resumed.active_task)
        self.assertEqual(resumed.activate_next().target, "interrupted")
        self.assertEqual(resumed.pending_count, 1)
        resumed.finish_active()
        self.assertEqual(resumed.activate_next().target, "pending")

    def test_checkpoint_during_activation_never_loses_or_duplicates_a_target(self):
        state = ScanRunState(["first", "second"])
        snapshots = self._snapshots_during(state, state.activate_next)
        self.assertTrue(snapshots)
        for snapshot in snapshots:
            self.assertEqual(snapshot, ["first", "second"])

    def test_checkpoint_during_preparation_sees_whole_old_or_new_queue(self):
        state = ScanRunState(["finished", "old"])
        state.activate_next()
        state.finish_active()
        snapshots = self._snapshots_during(state, state.prepare_targets, ["new", "next"])
        self.assertTrue(snapshots)
        for snapshot in snapshots:
            self.assertIn(snapshot, (["old"], ["new", "next"]))
        self.assertEqual([task.target for task in state.snapshot_tasks()], ["new", "next"])

    def _snapshots_during(self, state, transition, *args):
        snapshots = []

        def checkpoint_between_bytecodes(frame, event, _arg):
            if frame.f_code is transition.__code__:
                frame.f_trace_opcodes = True
                if event == "opcode":
                    # Model a reentrant Ctrl+C checkpoint without delivering
                    # process-wide signals or relying on scheduler timing.
                    snapshots.append([task.target for task in state.snapshot_tasks()])
            return checkpoint_between_bytecodes

        previous_trace = sys.gettrace()
        # Python 3.12 requires opcode tracing on an existing frame before
        # settrace(): https://docs.python.org/3.12/library/sys.html#sys.settrace
        current_frame = sys._getframe()
        previous_opcodes = current_frame.f_trace_opcodes
        current_frame.f_trace_opcodes = True
        sys.settrace(checkpoint_between_bytecodes)
        try:
            transition(*args)
        finally:
            current_frame.f_trace_opcodes = previous_opcodes
            sys.settrace(previous_trace)

        return snapshots
