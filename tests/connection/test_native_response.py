from unittest import TestCase

from lib.connection.response import NativeResponse


class TestNativeResponse(TestCase):
    def test_native_response_decodes_text_body(self):
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("Content-Type", "text/plain"), ("Content-Length", "2")],
            b"ok",
            0.125,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.full_path, "admin")
        self.assertEqual(response.length, 2)
        self.assertEqual(response.content, "ok")
        self.assertEqual(response.headers.get("content-type"), "text/plain")
        self.assertEqual(response.elapsed, 0.125)

    def test_native_response_uses_location_as_redirect(self):
        response = NativeResponse(
            "https://example.com/admin",
            302,
            [("Location", "/login")],
            b"",
        )

        self.assertEqual(response.redirect, "/login")
