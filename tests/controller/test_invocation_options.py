"""CLI preparation owns mutable input; execution never borrows caller state."""

import importlib.util
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from lib.controller.controller import Controller
from lib.core.option_defaults import default_options
from lib.core.settings import DEFAULT_HEADERS


class TestInvocationOptions(TestCase):
    def values(self, **changes):
        values = default_options()
        values.update(
            urls=[], wordlists=[], wordlist_backend="python", output_formats=[],
            async_mode=False, color=False, quiet=True,
        )
        values.update(changes)
        return values

    def test_defaults_do_not_share_mutable_containers(self):
        first, second = default_options(), default_options()
        for key, value in first.items():
            if isinstance(value, (dict, list, set)):
                with self.subTest(key=key):
                    self.assertIsNot(value, second[key])
        first["headers"]["Authorization"] = "Bearer first-only"
        first["urls"].append("https://first.test/")
        first["exclude_status_codes"].add(404)
        self.assertEqual(second, default_options())

    def test_repeated_cli_calls_pass_fresh_complete_input(self):
        spec = importlib.util.spec_from_file_location(
            "cli_options_test", Path(__file__).resolve().parents[2] / "dirsearch.py"
        )
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        first = {"headers": {"X-First": "one"}, "first_only": True}
        second = {"headers": {"X-Second": "two"}}
        with (
            patch.object(cli, "parse_options", side_effect=[first, second]),
            patch("lib.controller.controller.Controller") as factory,
        ):
            cli.main()
            cli.main()
        self.assertEqual(factory.call_count, 2)
        self.assertTrue(factory.call_args_list[0].args, "CLI must pass its input explicitly")
        first_input, second_input = [call.args[0] for call in factory.call_args_list]
        self.assertIsNot(first_input, second_input)
        self.assertTrue(first_input["first_only"])
        self.assertNotIn("first_only", second_input)
        self.assertEqual(first_input["headers"], {"X-First": "one"})
        self.assertEqual(second_input["headers"], {"X-Second": "two"})
        self.assertEqual(second_input["session_file"], None)

    def test_controllers_capture_nested_input_before_interleaved_preparation(self):
        values = self.values(headers={"X-Owner": "first"})
        first = Controller(values, output=StringIO())
        values["headers"]["X-Owner"] = "second"
        second = Controller(values, output=StringIO())
        values["headers"].clear()
        values["http_method"] = "DELETE"
        with patch.object(Controller, "_run_targets"):
            second.run()
            first.run()
        for controller, owner in ((first, "first"), (second, "second")):
            self.assertIn(("X-Owner", owner), controller.config.request.headers)
            self.assertEqual(controller.config.request.method, "GET")
            self.assertEqual(controller.session_options.to_options()["headers"]["X-Owner"], owner)
        self.assertIsNot(first.resources, second.resources)

    def test_raw_preparation_does_not_modify_caller_input(self):
        with TemporaryDirectory() as directory:
            raw = Path(directory, "request.txt")
            raw.write_bytes(b"POST /api HTTP/1.1\r\nHost: raw.test\r\n\r\nbody")
            values = self.values(raw_file=str(raw), headers={"X-Caller": "untouched"})
            before = deepcopy(values)
            controller = Controller(values, output=StringIO())
            with patch.object(controller, "_run_targets"):
                controller.run()
        self.assertEqual(values, before)
        self.assertEqual(controller.config.request.method, "POST")
        self.assertEqual(controller.config.request.body, b"body")
        self.assertIn(("host", "raw.test"), controller.config.request.headers)

    def test_header_overrides_leave_defaults_unchanged_for_all_engine_policies(self):
        for backend, async_mode in (("python", False), ("python", True), ("native", False)):
            with self.subTest(backend=backend, async_mode=async_mode):
                values = self.values(
                    request_backend=backend, async_mode=async_mode,
                    headers={"accept": "application/json", "x-owner": "first"},
                )
                first = Controller(values, output=StringIO())
                second = Controller({**values, "headers": {}}, output=StringIO())
                # Preparation is real; transport execution is out of scope here.
                with patch.object(Controller, "_run_targets"):
                    first.run()
                    second.run()
                self.assertEqual(dict(first.config.request.headers)["accept"], "application/json")
                self.assertEqual(dict(second.config.request.headers), dict(DEFAULT_HEADERS))
                self.assertEqual(DEFAULT_HEADERS["accept"], "*/*")
                self.assertNotIn("x-owner", DEFAULT_HEADERS)

    def test_failed_preparation_cannot_contaminate_another_owner(self):
        values = self.values()
        first = Controller(values, output=StringIO())
        second = Controller(values, output=StringIO())

        def fail_after_mutation():
            first._options["headers"]["Authorization"] = "Bearer failed-owner"
            first._options["session_file"] = "failed-session.json"
            raise ValueError("preparation failed")

        with patch.object(first, "_prepare", side_effect=fail_after_mutation):
            with self.assertRaisesRegex(ValueError, "preparation failed"):
                first.run()
        with patch.object(second, "_run_targets"):
            second.run()
        self.assertNotIn("Authorization", second.session_options.to_options()["headers"])
        self.assertIsNone(second.session_options.to_options()["session_file"])
        self.assertEqual(values["headers"], {})

    def test_invalid_resume_mutates_only_its_own_preparation_input(self):
        from lib.controller.session_options import SessionOptions
        from lib.controller.session_snapshot import RunCheckpoint, SessionSnapshot
        from lib.core.task_checkpoint import DictionaryCheckpoint, TaskCheckpoint

        values = self.values(session_file="checkpoint.json")
        before = deepcopy(values)
        snapshot = SessionSnapshot(
            run=RunCheckpoint(0), task_checkpoint=TaskCheckpoint(DictionaryCheckpoint((), 0)),
            options=SessionOptions({"timeout": -1, "headers": {"X-Saved": "value"}}),
        )
        store = Mock(load=Mock(return_value=snapshot))
        with (
            patch("lib.controller.controller.SessionStore", return_value=store),
            patch("sys.stderr", new_callable=StringIO),
            self.assertRaises(SystemExit),
        ):
            Controller(values, output=StringIO()).run()
        self.assertEqual(values, before)
