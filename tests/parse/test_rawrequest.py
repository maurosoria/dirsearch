from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from lib.parse.rawrequest import parse_raw


class TestRawRequestParser(TestCase):
    def _write_raw_request(self, directory: str, raw_request: str) -> str:
        request_file = Path(directory, "request.txt")
        request_file.write_bytes(raw_request.encode("utf-8"))
        return str(request_file)

    def test_origin_form_request_target(self):
        with TemporaryDirectory() as directory:
            request_file = self._write_raw_request(
                directory,
                "GET /admin HTTP/1.1\r\n"
                "Host: example.com\r\n"
                "\r\n",
            )

            urls, method, headers, body = parse_raw(request_file)

        self.assertEqual(urls, ["example.com/admin"])
        self.assertEqual(method, "GET")
        self.assertEqual(headers, {"host": "example.com"})
        self.assertEqual(body, "")

    def test_absolute_form_request_target(self):
        with TemporaryDirectory() as directory:
            request_file = self._write_raw_request(
                directory,
                "GET http://example.com/admin?debug=true HTTP/1.1\r\n"
                "Host: proxy.local\r\n"
                "\r\n",
            )

            urls, method, headers, body = parse_raw(request_file)

        self.assertEqual(urls, ["example.com/admin?debug=true"])
        self.assertEqual(method, "GET")
        self.assertEqual(headers, {"host": "proxy.local"})
        self.assertEqual(body, "")
