import os
import tempfile
from unittest import TestCase

from lib.core.data import options
from lib.core.logger import enable_logging, logger, redact_log_text


class TestLogRedaction(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        self.original_handlers = tuple(logger.handlers)
        self.original_disabled = logger.disabled
        for handler in self.original_handlers:
            logger.removeHandler(handler)

    def tearDown(self):
        for handler in tuple(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        for handler in self.original_handlers:
            logger.addHandler(handler)
        logger.disabled = self.original_disabled
        options.clear()
        options.update(self.original_options)

    def test_redacts_url_secrets_without_hiding_request_metadata(self):
        options["proxy_auth"] = "proxy-user:scheme-less-password"
        message = (
            '"GET https://alice:target-password@example.test/admin'
            '?=empty-key-secret&token=query-secret&mode=debug&bare-secret" '
            "200 - 42B - "
            "LOCATION: /login?code=redirect-secret&empty= - "
            "PROXIES: socks5://encoded-user:p%3Ass@[2001:db8::1]:1080/ "
            "proxy-user:scheme-less-password@proxy.example.test"
        )

        self.assertEqual(
            redact_log_text(message),
            '"GET https://<redacted>@example.test/admin'
            '?=<redacted>&token=<redacted>&mode=<redacted>&<redacted>" '
            "200 - 42B - "
            "LOCATION: /login?code=<redacted>&empty=<redacted> - "
            "PROXIES: socks5://<redacted>@[2001:db8::1]:1080/ "
            "<redacted>@proxy.example.test",
        )

    def test_file_formatter_redacts_traceback_and_configured_proxy_auth(self):
        proxy_auth = "proxy-user:proxy-password/segment"
        with tempfile.TemporaryDirectory() as root:
            log_path = os.path.join(root, "dirsearch.log")
            options["log_file"] = log_path
            options["log_file_size"] = 0
            options["proxy_auth"] = proxy_auth
            enable_logging()

            logger.info(
                '"GET https://target-user:target-password@target.example.test/path'
                '?token=query-secret&debug=true" 200 - 42B'
            )
            try:
                raise ValueError(
                    f"Invalid proxy URL: http://{proxy_auth}"
                    "@proxy.example.test:8080"
                )
            except ValueError as error:
                logger.exception(error)
            logger.info('THREAD-7 started')

            for handler in logger.handlers:
                handler.flush()
            with open(log_path, encoding="utf-8") as log_file:
                contents = log_file.read()

        for secret in (
            "target-password",
            "query-secret",
            "true",
            "proxy-password",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, contents)

        self.assertIn(
            "GET https://<redacted>@target.example.test/path",
            contents,
        )
        self.assertIn("?token=<redacted>&debug=<redacted>", contents)
        self.assertIn("proxy.example.test:8080", contents)
        self.assertIn("Traceback (most recent call last)", contents)
        self.assertIn("ValueError: Invalid proxy URL", contents)
        self.assertIn("THREAD-7 started", contents)
