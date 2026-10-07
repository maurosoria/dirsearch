from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from lib.controller.controller import Controller
from lib.core.data import options


class TestControllerRequestConfig(TestCase):
    def test_requester_is_configured_after_setup_or_session_restore(self):
        for backend, async_mode, requester_path in (
            ("python", False, "lib.connection.requester.Requester"),
            ("python", True, "lib.connection.requester.AsyncRequester"),
            ("native", False, "lib.connection.native.NativeRequester"),
        ):
            for resumed in (False, True):
                with self.subTest(backend=backend, async_mode=async_mode, resumed=resumed):
                    def prepare(controller, *_args):
                        # Raw parsing and session restoration both finish before
                        # run() constructs the transport's immutable baseline.
                        options.update(
                            http_method="PATCH", data=b"prepared-body",
                            headers={"X-Prepared": "yes"}, timeout=3,
                            session_file=None, urls=[],
                        )
                        controller._prepare_config(options)
                        controller.resources.reporter = Mock(reports=())

                    requester = Mock()
                    if async_mode:
                        requester.close = AsyncMock()
                    with (
                        patch.dict(options, {
                            "request_backend": backend, "async_mode": async_mode,
                            "session_file": "session.json" if resumed else None,
                            "http_method": "GET", "data": None, "headers": {},
                        }),
                        patch.object(Controller, "setup", new=prepare),
                        patch.object(Controller, "_import", new=prepare),
                        patch(requester_path, return_value=requester) as factory,
                        patch("lib.controller.controller.signal.signal"),
                        patch("lib.controller.controller.create_terminal"),
                    ):
                        controller = Controller()
                        controller.run()
                        options["headers"]["X-Prepared"] = "changed"
                        options["http_method"] = "DELETE"

                    factory.assert_called_once()
                    if backend == "python":
                        self.assertIs(factory.call_args.kwargs["logger"], controller.resources.logger)
                    config = factory.call_args.args[0]
                    self.assertIs(config, controller.config.request)
                    self.assertEqual(config.method, "PATCH")
                    self.assertEqual(config.body, b"prepared-body")
                    self.assertEqual(config.headers, (("X-Prepared", "yes"),))
                    self.assertEqual(config.timeout, 3)
