from dataclasses import FrozenInstanceError
from unittest import TestCase
from unittest.mock import patch

from lib.core.run_metadata import RunMetadata


class TestRunMetadata(TestCase):
    def test_capture_detaches_and_redacts_arguments(self):
        arguments = [
            "dirsearch", "-u", "https://user:target-secret@example.test/",
            "--auth", "user:auth-secret", "-H", "Authorization: Bearer header-secret",
            "--proxy-auth=proxy-secret", "--cookie", "session=cookie-secret",
            "--data", "body-secret",
        ]
        with patch("lib.core.run_metadata.time.strftime", return_value="2026-10-06 12:34:56"):
            metadata = RunMetadata.capture(arguments)
        arguments[:] = ["unrelated"]

        self.assertEqual(metadata.command, (
            "dirsearch -u <redacted> --auth <redacted> -H <redacted> "
            "--proxy-auth=<redacted> --cookie <redacted> --data <redacted>"
        ))
        self.assertEqual(metadata.start_time, "2026-10-06 12:34:56")
        self.assertNotIn("command=", repr(metadata))
        with self.assertRaises(FrozenInstanceError):
            metadata.command = "changed"

    def test_empty_arguments_do_not_fall_back_to_process_arguments(self):
        with patch("sys.argv", ["unrelated", "--auth", "private-value"]):
            self.assertEqual(RunMetadata.capture([]).command, "")
            self.assertEqual(RunMetadata.capture().command, "unrelated --auth <redacted>")

    def test_each_capture_uses_its_own_clock_value(self):
        with patch("lib.core.run_metadata.time.strftime", side_effect=["first", "second"]) as clock:
            first = RunMetadata.capture(["dirsearch", "-u", "https://first.test/"])
            second = RunMetadata.capture(["dirsearch", "-u", "https://second.test/"])
        self.assertEqual((first.start_time, second.start_time), ("first", "second"))
        self.assertNotEqual(first.command, second.command)
        self.assertEqual(clock.call_count, 2)
