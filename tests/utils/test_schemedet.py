#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from unittest import TestCase
from unittest.mock import Mock, patch

from lib.core.settings import SOCKET_TIMEOUT
from lib.utils.schemedet import detect_scheme


class TestSchemedet(TestCase):
    def run_probe(self, connect_error=None):
        raw_socket = Mock()
        connection = Mock()
        connection.connect.side_effect = connect_error
        context = Mock()
        context.wrap_socket.return_value = connection

        with patch(
            "lib.utils.schemedet.socket.socket", return_value=raw_socket
        ) as socket_factory, patch(
            "lib.utils.schemedet.ssl.create_default_context", return_value=context
        ) as context_factory:
            scheme = detect_scheme("example.test", 443)

        socket_factory.assert_called_once_with()
        raw_socket.settimeout.assert_called_once_with(SOCKET_TIMEOUT)
        context_factory.assert_called_once_with()
        context.wrap_socket.assert_called_once_with(
            raw_socket, server_hostname="example.test"
        )
        connection.connect.assert_called_once_with(("example.test", 443))
        connection.close.assert_called_once_with()

        return scheme

    def test_detects_https_when_tls_connection_succeeds(self):
        self.assertEqual(self.run_probe(), "https")

    def test_falls_back_to_http_when_tls_connection_fails(self):
        self.assertEqual(self.run_probe(OSError("network unavailable")), "http")
