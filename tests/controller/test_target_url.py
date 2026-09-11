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
            ("http://[::]/", "http://[::]/"),
            ("http://[::1]/", "http://[::1]/"),
            (
                "http://[0:0:0:0:0:0:0:1]/",
                "http://[0:0:0:0:0:0:0:1]/",
            ),
            (
                "http://[2001:0db8:0000:0000:0000:ff00:0042:8329]/",
                "http://[2001:0db8:0000:0000:0000:ff00:0042:8329]/",
            ),
            (
                "http://[2001:db8::ff00:42:8329]/",
                "http://[2001:db8::ff00:42:8329]/",
            ),
            ("http://[2001:db8::]/", "http://[2001:db8::]/"),
            ("http://[2001:DB8::ABCD]/", "http://[2001:db8::abcd]/"),
            (
                "http://[::ffff:192.0.2.128]/",
                "http://[::ffff:192.0.2.128]/",
            ),
            (
                "http://[64:ff9b::192.0.2.33]/",
                "http://[64:ff9b::192.0.2.33]/",
            ),
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

    def test_scheme_option_keeps_ipv6_literal_brackets(self):
        options["scheme"] = "https"

        self.controller.set_target("[2001:db8::1]:8443/private")

        self.assertEqual(self.controller.url, "https://[2001:db8::1]:8443/")
        self.controller.requester.set_url.assert_called_once_with(
            "https://[2001:db8::1]:8443/"
        )
