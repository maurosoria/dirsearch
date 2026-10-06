from dataclasses import FrozenInstanceError
from unittest import TestCase

from lib.controller.session_snapshot import RunCheckpoint
from lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint


class TestTaskCheckpoint(TestCase):
    def test_checkpoints_own_immutable_sequences_without_normalizing_input(self):
        items = ["first", "first", "a%2Fb", "café"]
        extra = ["extra", "extra"]
        directories = ["current/", "next/", "next/"]
        passed_urls = ["http://example.test/current/"]
        dictionary = DictionaryCheckpoint(items, 1, extra, 1)
        task = TaskCheckpoint(dictionary, "http://[::1]:8080/", "base/", directories)
        run = RunCheckpoint(12, passed_urls)
        items.clear()
        extra.clear()
        directories.clear()
        passed_urls.clear()
        self.assertEqual(dictionary.items, ("first", "first", "a%2Fb", "café"))
        self.assertEqual(dictionary.extra, ("extra", "extra"))
        self.assertEqual(task.directories, ("current/", "next/", "next/"))
        self.assertEqual(task.url, "http://[::1]:8080/")
        self.assertEqual(task.base_path, "base/")
        self.assertEqual(run.passed_urls, ("http://example.test/current/",))
        with self.assertRaises(FrozenInstanceError):
            dictionary.index = 2
        with self.assertRaises(FrozenInstanceError):
            task.url = "changed"
        with self.assertRaises(FrozenInstanceError):
            run.errors = 1

    def test_restored_dictionary_containers_are_independent(self):
        checkpoint = DictionaryCheckpoint(["done", "pending"], 1, ["extra"], 0)
        first = checkpoint.to_state()
        second = checkpoint.to_state()
        first[0].clear()
        first[2].clear()
        self.assertEqual(second, (["done", "pending"], 1, ["extra"], 0))
        self.assertEqual(checkpoint.to_state(), second)

    def test_repr_does_not_include_paths_or_wordlist_contents(self):
        checkpoint = DictionaryCheckpoint(["private-item"], 0, ["private-extra"], 0)
        task = TaskCheckpoint(checkpoint, "http://user:secret@example.test/", "private-base", ["private-dir"])
        self.assertEqual(repr(task), "TaskCheckpoint()")
        self.assertEqual(repr(checkpoint), "DictionaryCheckpoint(index=0, extra_index=0)")
        self.assertNotIn("secret", repr(RunCheckpoint(0, ["secret"])))
