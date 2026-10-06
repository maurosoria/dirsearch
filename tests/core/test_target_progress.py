from unittest import TestCase

from lib.core.target_progress import TargetProgress


class TestTargetProgress(TestCase):
    def test_default_instances_own_independent_directory_queues(self):
        first = TargetProgress()
        second = TargetProgress()
        first.directories.append("api/")
        first.url = "http://first.test/"
        first.base_path = "api/"
        self.assertEqual(second, TargetProgress())
        self.assertEqual(first.directories, ["api/"])

    def test_constructor_detaches_input_without_normalizing_order_or_text(self):
        directories = ["a%2Fb/", "", "café/", "a%2Fb/"]
        progress = TargetProgress("http://[::1]:8080/", "a%2Fb/", directories)
        directories.clear()
        self.assertEqual(progress.directories, ["a%2Fb/", "", "café/", "a%2Fb/"])
        self.assertEqual(progress.url, "http://[::1]:8080/")
        self.assertEqual(progress.base_path, "a%2Fb/")

    def test_two_targets_do_not_share_a_supplied_queue(self):
        directories = ["current/", "next/"]
        first = TargetProgress(directories=directories)
        second = TargetProgress(directories=directories)
        first.directories.pop(0)
        self.assertEqual(second.directories, directories)
