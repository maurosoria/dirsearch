from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

import requests

from lib.connection.requester import AsyncRequester, Requester
from lib.controller.controller import Controller
from lib.core.data import options
from lib.core.exceptions import InvalidURLException


class TestControllerTargetCredentials(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "request_backend": "python",
                "scheme": None,
                "ip": None,
            }
        )
        self.controller = object.__new__(Controller)
        self.controller.requester = Mock()

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_embedded_basic_credentials_are_parsed_and_decoded(self):
        cases = (
            ("http://user:pass@example.test/", "user:pass"),
            (
                "http://user%40name:p%40ss%3Aword@example.test/",
                "user@name:p@ss:word",
            ),
            ("http://user:p@ss@example.test/", "user:p@ss"),
            ("http://user@example.test/", "user"),
            ("http://:pass@example.test/", ":pass"),
        )

        for target, credential in cases:
            with self.subTest(target=target):
                self.controller.requester.reset_mock()

                self.controller.set_target(target)

                self.controller.requester.reset_auth.assert_called_once_with()
                self.controller.requester.set_auth.assert_called_once_with(
                    "basic", credential
                )
                self.controller.requester.set_url.assert_called_once_with(
                    "http://example.test/"
                )

    def test_target_path_and_query_survive_credential_removal(self):
        self.controller.set_target(
            "https://user:pass@example.test/private?debug=true"
        )

        self.assertEqual(self.controller.base_path, "private/")
        self.controller.requester.reset_auth.assert_called_once_with()
        self.controller.requester.set_url.assert_called_once_with(
            "https://example.test/"
        )
        self.controller.requester.set_query.assert_called_once_with("debug=true")

    def test_scheme_less_target_supports_embedded_credentials(self):
        with patch(
            "lib.controller.controller.detect_scheme",
            side_effect=(ValueError, "https"),
        ):
            self.controller.set_target("user:p%40ss@example.test")

        self.controller.requester.set_auth.assert_called_once_with(
            "basic", "user:p@ss"
        )
        self.controller.requester.reset_auth.assert_called_once_with()
        self.controller.requester.set_url.assert_called_once_with(
            "https://example.test/"
        )

    def test_target_without_credentials_restores_configured_authentication(self):
        self.controller.set_target("https://example.test/")

        self.controller.requester.reset_auth.assert_called_once_with()
        self.controller.requester.set_auth.assert_not_called()
        self.controller.requester.set_url.assert_called_once_with(
            "https://example.test/"
        )

    def test_rejected_target_does_not_change_authentication(self):
        with self.assertRaisesRegex(InvalidURLException, "Unsupported URI scheme"):
            self.controller.set_target(
                "ftp://target-user:target-password@example.test/"
            )

        self.controller.requester.reset_auth.assert_not_called()
        self.controller.requester.set_auth.assert_not_called()


class TargetAuthenticationIntegrationMixin:
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "request_backend": "python",
                "scheme": None,
                "ip": None,
                "proxies": [],
                "tor": False,
                "proxy_auth": None,
                "headers": {},
                "cert_file": None,
                "key_file": None,
                "network_interface": None,
                "random_agents": False,
                "data": None,
                "auth": None,
                "auth_type": None,
                "thread_count": 1,
                "timeout": 1,
            }
        )

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    @staticmethod
    def controller_for(requester):
        controller = object.__new__(Controller)
        controller.requester = requester
        return controller


class TestSyncTargetAuthenticationIntegration(
    TargetAuthenticationIntegrationMixin, TestCase
):
    def test_embedded_authentication_does_not_persist_to_next_target(self):
        requester = Requester()
        controller = self.controller_for(requester)
        try:
            controller.set_target("http://target-user:target-password@first.test/")
            self.assertIsNotNone(requester.session.auth)

            controller.set_target("http://second.test/")

            self.assertIsNone(requester.session.auth)
        finally:
            requester.close()

    def test_configured_authentication_is_restored_after_target_override(self):
        options.update(
            {
                "auth": "global-user:global-password",
                "auth_type": "basic",
            }
        )
        requester = Requester()
        configured_auth = requester.session.auth
        controller = self.controller_for(requester)
        try:
            controller.set_target("http://target-user:target-password@first.test/")
            self.assertIsNot(requester.session.auth, configured_auth)

            controller.set_target("http://second.test/")

            self.assertIs(requester.session.auth, configured_auth)
        finally:
            requester.close()

    def test_explicit_authorization_header_survives_target_override(self):
        options["headers"] = {"Authorization": "Bearer configured-token"}
        requester = Requester()
        controller = self.controller_for(requester)
        try:
            controller.set_target("http://target-user:target-password@first.test/")
            target_request = requester.session.prepare_request(
                requests.Request("GET", requester._url, headers=requester.headers)
            )
            self.assertEqual(
                target_request.headers["Authorization"],
                "Basic dGFyZ2V0LXVzZXI6dGFyZ2V0LXBhc3N3b3Jk",
            )

            controller.set_target("http://second.test/")
            configured_request = requester.session.prepare_request(
                requests.Request("GET", requester._url, headers=requester.headers)
            )

            self.assertEqual(
                configured_request.headers["Authorization"],
                "Bearer configured-token",
            )
        finally:
            requester.close()


class TestAsyncTargetAuthenticationIntegration(
    TargetAuthenticationIntegrationMixin, IsolatedAsyncioTestCase
):
    async def test_embedded_authentication_does_not_persist_to_next_target(self):
        requester = AsyncRequester()
        controller = self.controller_for(requester)
        try:
            controller.set_target("http://target-user:target-password@first.test/")
            self.assertIsNotNone(requester.session.auth)

            controller.set_target("http://second.test/")

            self.assertIsNone(requester.session.auth)
        finally:
            await requester.close()

    async def test_configured_authentication_is_restored_after_target_override(self):
        options.update(
            {
                "auth": "global-user:global-password",
                "auth_type": "basic",
            }
        )
        requester = AsyncRequester()
        configured_auth = requester.session.auth
        controller = self.controller_for(requester)
        try:
            controller.set_target("http://target-user:target-password@first.test/")
            self.assertIsNot(requester.session.auth, configured_auth)

            controller.set_target("http://second.test/")

            self.assertIs(requester.session.auth, configured_auth)
        finally:
            await requester.close()

    async def test_explicit_authorization_header_survives_target_override(self):
        options["headers"] = {"Authorization": "Bearer configured-token"}
        requester = AsyncRequester()
        controller = self.controller_for(requester)
        try:
            controller.set_target("http://target-user:target-password@first.test/")
            self.assertEqual(
                requester.headers["Authorization"],
                "Bearer configured-token",
            )

            controller.set_target("http://second.test/")

            self.assertIsNone(requester.session.auth)
            self.assertEqual(
                requester.headers["Authorization"],
                "Bearer configured-token",
            )
        finally:
            await requester.close()
