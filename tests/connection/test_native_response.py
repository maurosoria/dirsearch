# -*- coding: utf-8 -*-

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

    def test_native_cjk_length_uses_network_bytes(self):
        body = "测试".encode()
        response = NativeResponse(
            "https://example.com/admin/%E6%B5%8B%E8%AF%95",
            200,
            [("Content-Length", str(len(body)))],
            body,
        )

        self.assertEqual(response.content, "测试")
        self.assertEqual(len(response.content), 2)
        self.assertEqual(response.length, 6)

    def test_native_case_expansion_length_uses_network_bytes(self):
        body = "/TEST-STRASSE".encode()
        response = NativeResponse(
            "https://example.com/test-stra%C3%9Fe",
            200,
            [("Content-Length", str(len(body)))],
            body,
        )

        self.assertEqual(response.content, "/TEST-STRASSE")
        self.assertEqual(response.length, len(body))

    def test_native_invalid_utf8_uses_replacement_decoding(self):
        response = NativeResponse(
            "https://example.com/admin",
            200,
            [("Content-Type", "text/html; charset=utf-8")],
            b"start\x96end",
        )

        self.assertEqual(response.body, b"start\x96end")
        self.assertEqual(response.content, "start�end")
        self.assertEqual(response.length, len(response.body))

    def test_native_utf16_bom_artifact_body_does_not_raise_decode_error(self):
        response = NativeResponse(
            "https://example.com/%FF%FEadmin",
            200,
            [],
            b"\xff\xfeadmin",
        )

        self.assertEqual(response.body, b"\xff\xfeadmin")
        self.assertEqual(response.content, "��admin")
        self.assertEqual(response.length, len(response.body))

    def test_native_filtered_response_keeps_explicit_length_without_body(self):
        response = NativeResponse(
            "https://example.com/missing",
            404,
            [("content-type", "text/plain")],
            [],
            length=123,
            filtered=True,
            filter_reason="advanced_filter",
        )

        self.assertTrue(response.filtered)
        self.assertEqual(response.filter_reason, "advanced_filter")
        self.assertEqual(response.body, b"")
        self.assertEqual(response.length, 123)

    def test_truncated_native_responses_do_not_compare_as_complete_bodies(self):
        prefix = b"\x00" + b"a" * 15
        left = NativeResponse(
            "https://example.com/left.bin",
            200,
            [("Content-Length", str(len(prefix) + 4))],
            prefix,
            length=len(prefix) + 4,
        )
        right = NativeResponse(
            "https://example.com/right.bin",
            200,
            [("Content-Length", str(len(prefix) + 4))],
            prefix,
            length=len(prefix) + 4,
        )

        self.assertNotEqual(left, right)
        self.assertFalse(left.body_complete)
        self.assertTrue(left.body_truncated)
