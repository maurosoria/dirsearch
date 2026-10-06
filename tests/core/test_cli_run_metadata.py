import importlib.util
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from lib.core.data import options
from lib.core.run_metadata import RunMetadata


class TestCLIRunMetadata(TestCase):
    def test_repeated_main_calls_capture_before_option_preparation(self):
        spec = importlib.util.spec_from_file_location(
            "cli_metadata_test", Path(__file__).resolve().parents[2] / "dirsearch.py"
        )
        cli = importlib.util.module_from_spec(spec)
        with patch.object(RunMetadata, "capture") as capture:
            spec.loader.exec_module(cli)
        capture.assert_not_called()

        def prepare_options():
            sys.argv[:] = ["changed-after-entry"]
            return {"wordlist_status": False, "session_file": None}

        # main() still writes the transitional global options dictionary.
        with (
            patch.dict(options, {}, clear=True),
            patch.object(cli, "parse_options", side_effect=prepare_options),
            patch("lib.controller.controller.Controller") as controller,
        ):
            for name in ("first", "second"):
                with (
                    patch("sys.argv", ["dirsearch", "--auth", name + "-secret", "-w", name]),
                    patch("time.strftime", return_value=name + "-date"),
                ):
                    cli.main()
        self.assertEqual(controller.call_count, 2)
        for call, name in zip(controller.call_args_list, ("first", "second")):
            metadata = call.kwargs["metadata"]
            self.assertEqual(metadata.command, "dirsearch --auth <redacted> -w " + name)
            self.assertEqual(metadata.start_time, name + "-date")
