"""Bounded, proxy-independent runner for same-process lifecycle scenarios."""

import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase


class TestLifecycleAcceptance(TestCase):
    def run_scenario(self, method):
        # Each scenario keeps its controllers in ONE process. Use a child-owned
        # environment rather than changing the test runner's process globals or
        # allowing inherited proxies to receive loopback test traffic.
        environment = os.environ.copy()
        for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
            environment.pop(name, None)
        environment.update(NO_PROXY="*", no_proxy="*")
        completed = subprocess.run(
            [sys.executable, "-m", "tests.controller.lifecycle_scenarios", "LifecycleScenarios." + method],
            cwd=Path(__file__).resolve().parents[2], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=45, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_complete_runs_keep_input_output_reports_and_resources_independent(self):
        self.run_scenario("test_complete_runs_keep_input_output_reports_and_resources_independent")

    def test_callback_output_failure_closes_real_resources_and_does_not_poison_next_run(self):
        self.run_scenario("test_callback_output_failure_closes_real_resources_and_does_not_poison_next_run")

    def test_deadline_drains_workers_before_a_different_engine_runs(self):
        self.run_scenario("test_deadline_drains_workers_before_a_different_engine_runs")

    def test_failed_storage_preparation_closes_acquired_resources_without_starting_requests(self):
        self.run_scenario("test_failed_storage_preparation_closes_acquired_resources_without_starting_requests")

    def test_saved_continuation_resumes_current_job_then_resets_for_later_work(self):
        self.run_scenario("test_saved_continuation_resumes_current_job_then_resets_for_later_work")
