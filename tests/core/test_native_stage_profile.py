from unittest import TestCase

from scripts.profile_native_processing import StageTimer


class TestStageTimer(TestCase):
    def test_nested_stage_time_is_not_double_counted(self):
        ticks = iter([0, 2, 7, 10])
        timer = StageTimer(clock=lambda: next(ticks))
        inner = timer.wrap('inner', lambda: 42)
        outer = timer.wrap('outer', inner)
        self.assertEqual(outer(), 42)
        self.assertEqual(timer.totals['inner'], dict(calls=1, inclusive_ns=5, exclusive_ns=5))
        self.assertEqual(timer.totals['outer'], dict(calls=1, inclusive_ns=10, exclusive_ns=5))

    def test_exception_still_records_cpu_and_restores_the_stack(self):
        ticks = iter([1, 4, 5, 9])
        timer = StageTimer(clock=lambda: next(ticks))

        def fail():
            raise ValueError('example')
        with self.assertRaises(ValueError):
            timer.wrap('failed', fail)()
        self.assertEqual(timer.wrap('next', lambda: 'ok')(), 'ok')
        self.assertEqual(timer.totals['failed']['exclusive_ns'], 3)
        self.assertEqual(timer.totals['next']['exclusive_ns'], 4)
