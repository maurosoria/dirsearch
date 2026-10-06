from dataclasses import FrozenInstanceError
from unittest import TestCase

from lib.core.task_spec import TaskSpec


class TestTaskSpec(TestCase):
    def test_preserves_input_until_target_preparation_validates_it(self):
        for target in (
            "", "not a URL", "example.test/path", "https://example.test/a%2Fb?next=/home",
            "http://[2001:db8::1]:8080/", "https://example.test/café",
            "https://user:p%40ss@example.test/path?token=private-value#fragment",
        ):
            with self.subTest(target=target):
                self.assertEqual(TaskSpec(target).target, target)

    def test_input_cannot_change_after_construction(self):
        task = TaskSpec("https://example.test/")
        with self.assertRaises(FrozenInstanceError):
            task.target = "https://changed.test/"

    def test_repr_does_not_include_credentials_or_queries(self):
        task = TaskSpec("https://user:private-value@example.test/?token=private-token")
        self.assertEqual(repr(task), "TaskSpec()")
