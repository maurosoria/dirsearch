from unittest import TestCase
from unittest.mock import Mock

from lib.controller.controller import Controller
from lib.core.data import options


class TestControllerTargetURL(TestCase):
    def setUp(self):
        self.original_options = dict(options)
        options.update(
            {
                "request_backend": "python",
                "scheme": None,
                "ip": None,
                "proxies": [],
                "tor": False,
            }
        )
        self.controller = object.__new__(Controller)
        self.controller.requester = Mock()

    def tearDown(self):
        options.clear()
        options.update(self.original_options)

    def test_ipv6_target_authority_keeps_literal_brackets(self):
        cases = (
            ("http://[::1]/", "http://[::1]/"),
            (
                "https://[2001:db8::1]:443/private",
                "https://[2001:db8::1]/",
            ),
            (
                "http://[2001:db8::2]:8080/api",
                "http://[2001:db8::2]:8080/",
            ),
            (
                "http://[fe80::1%25eth0]:8000/",
                "http://[fe80::1%25eth0]:8000/",
            ),
        )

        for target, expected_url in cases:
            with self.subTest(target=target):
                self.controller.requester.reset_mock()

                self.controller.set_target(target)

                self.assertEqual(self.controller.url, expected_url)
                self.controller.requester.set_url.assert_called_once_with(
                    expected_url
                )
