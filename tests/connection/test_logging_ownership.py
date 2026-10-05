"""Request diagnostics borrow a run logger without owning its lifetime."""

import ssl
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from lib.connection.requester import AsyncRequester, Requester, _format_ssl_error
from lib.core.log_config import LogConfig
from lib.core.logger import RunLogger
from lib.core.request_config import RequestConfig
from tests.connection.test_requester import DummyAsyncResponse, DummySyncResponse


class TestRequesterLoggingOwnership(IsolatedAsyncioTestCase):
    async def test_request_messages_are_redacted_in_only_the_borrowed_log(self):
        with TemporaryDirectory() as directory:
            first_path = Path(directory, "threaded.log")
            second_path = Path(directory, "async.log")
            first = RunLogger(LogConfig(str(first_path)))
            second = RunLogger(LogConfig(str(second_path)))
            try:
                sync = Requester(RequestConfig(), logger=first)
                try:
                    sync.set_url("http://example.test/")
                    with patch.object(sync.session, "send", return_value=DummySyncResponse()):
                        sync.request("threaded?token=first-secret")
                finally:
                    sync.close()
                self.assertFalse(first.disabled)
                first.info("after sync close")

                asynchronous = AsyncRequester(RequestConfig(), logger=second)
                try:
                    asynchronous.set_url("http://example.test/")
                    with patch.object(asynchronous.session, "send", new=AsyncMock(return_value=DummyAsyncResponse())):
                        await asynchronous.request("asynchronous?token=second-secret")
                finally:
                    await asynchronous.close()
                self.assertFalse(second.disabled)
                second.info("after async close")
            finally:
                first.close()
                second.close()
            first_text = first_path.read_text()
            second_text = second_path.read_text()
            self.assertIn("GET http://example.test/threaded?token=<redacted>", first_text)
            self.assertIn("GET http://example.test/asynchronous?token=<redacted>", second_text)
            self.assertNotIn("first-secret", first_text)
            self.assertNotIn("second-secret", second_text)
            self.assertNotIn("asynchronous", first_text)
            self.assertNotIn("threaded", second_text)
            self.assertIn("after sync close", first_text)
            self.assertIn("after async close", second_text)

    def test_ssl_diagnostics_use_the_supplied_logger(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, "tls.log")
            logger = RunLogger(LogConfig(str(path)))
            try:
                message = _format_ssl_error(
                    ssl.SSLError("wrong version"),
                    "https://example.test/?token=secret", logger=logger,
                )
            finally:
                logger.close()
            self.assertIn("SSL protocol version mismatch", message)
            contents = path.read_text()
            self.assertIn("[WARNING] SSL error", contents)
            self.assertIn("?token=<redacted>", contents)
            self.assertNotIn("token=secret", contents)
