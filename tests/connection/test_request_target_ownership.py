"""Raw targets belong to requests, not the thread running their transports."""

import threading
from unittest.mock import patch

import requests
from urllib3.exceptions import ProtocolError
from urllib3.util.retry import Retry

from lib.connection.requester import PathPreservingHTTPConnectionPool, Requester
from lib.connection.request_target import RawRequestTarget, RequestTargetURL
from lib.core.exceptions import RequestException
from lib.core.request_config import RequestConfig
from tests.connection.test_requester import (
    BaseRequesterTestCase,
    RequestTargetHandler,
    RequestTargetServer,
)


class KeepAliveTargetHandler(RequestTargetHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(2)

    def do_GET(self):
        self.server.client_ports.append(self.client_address[1])
        super().do_GET()


class TestRequestTargetOwnership(BaseRequesterTestCase):
    def requester(self, url):
        requester = Requester(RequestConfig.from_options(self.options))
        requester.set_url(url)
        self.addCleanup(requester.close)
        return requester

    def test_nested_request_does_not_replace_or_delete_the_outer_target(self):
        with RequestTargetServer() as server:
            outer = self.requester(server.url)
            inner = self.requester(server.url)
            adapter = outer.session.get_adapter(server.url)

            def nested_request(_request, **_kwargs):
                self.assertEqual(inner.request("inner%1\\*").status, 200)

            with patch.object(adapter, "add_headers", side_effect=nested_request):
                response = outer.request("outer%2\\*")

            self.assertEqual(response.status, 200)
            self.assertEqual(server.targets, [b"/inner%1\\*", b"/outer%2\\*"])

    def test_unmarked_request_does_not_borrow_an_outer_raw_target(self):
        with RequestTargetServer() as server:
            outer = self.requester(server.url)
            inner = self.requester(server.url)
            adapter = outer.session.get_adapter(server.url)

            def ordinary_request(_request, **_kwargs):
                with inner.session.get(server.url + "ordinary", timeout=2) as response:
                    self.assertEqual(response.status_code, 200)

            with patch.object(adapter, "add_headers", side_effect=ordinary_request):
                response = outer.request("outer%1\\*")

            self.assertEqual(response.status, 200)
            self.assertEqual(server.targets, [b"/ordinary", b"/outer%1\\*"])

    def test_failed_nested_request_does_not_change_the_outer_target(self):
        with RequestTargetServer() as server:
            outer = self.requester(server.url)
            inner = self.requester(server.url)
            outer_adapter = outer.session.get_adapter(server.url)
            inner_adapter = inner.session.get_adapter(server.url)

            def failed_nested_request(_request, **_kwargs):
                with self.assertRaises(RequestException):
                    inner.request("failed%1")

            with (
                patch.object(outer_adapter, "add_headers", side_effect=failed_nested_request),
                patch.object(inner_adapter, "add_headers", side_effect=RuntimeError("injected")),
            ):
                response = outer.request("outer%1\\*")
            inner.request("after-failure%2")

            self.assertEqual(response.status, 200)
            self.assertEqual(server.targets, [b"/outer%1\\*", b"/after-failure%2"])

    def test_authentication_copy_retains_the_explicit_target(self):
        request = requests.Request("GET", "http://example.invalid/").prepare()
        request.url = RequestTargetURL("http://example.invalid/%1", "/%1")
        copied = request.copy()

        self.assertIsInstance(copied.url, RequestTargetURL)
        self.assertEqual(copied.url.request_target, "/%1")
        # Replacing the URL (as Requests does for redirects) drops the target.
        copied.url = "http://example.invalid/final"
        self.assertNotIsInstance(copied.url, RequestTargetURL)
        self.assertEqual(request.url.request_target, "/%1")

    def test_reused_socket_does_not_retain_a_previous_target(self):
        with RequestTargetServer(KeepAliveTargetHandler) as server:
            server.server.client_ports = []
            requester = self.requester(server.url)
            try:
                requester.request("first%1")
                with requester.session.get(server.url + "ordinary%1", timeout=2) as response:
                    self.assertEqual(response.status_code, 200)
                requester.session.headers["Connection"] = "close"
                requester.request("last%2")
            finally:
                # The fixture keeps this socket alive until the client closes it.
                requester.close()

            self.assertEqual(server.targets, [b"/first%1", b"/ordinary%251", b"/last%2"])
            self.assertEqual(len(set(server.server.client_ports)), 1)

    def test_digest_retry_preserves_the_wire_target(self):
        self.options.update(auth="digest-user:digest-password", auth_type="digest")
        with RequestTargetServer() as server:
            requester = self.requester(server.url)
            response = requester.request("digest-auth%1")

            self.assertEqual(response.status, 200)
            self.assertEqual(server.targets, [b"/digest-auth%1", b"/digest-auth%1"])
            self.assertIsNone(server.authorizations[0])
            self.assertIn('uri="/digest-auth%1"', server.authorizations[1])

    def test_redirect_does_not_reuse_the_initial_raw_target(self):
        self.options["follow_redirects"] = True
        with RequestTargetServer() as server:
            requester = self.requester(server.url)
            response = requester.request("redirect%1")

            self.assertEqual(response.status, 200)
            self.assertEqual(response.history, [server.url + "redirect%1"])
            self.assertEqual(server.targets, [b"/redirect%1", b"/final"])

    def test_body_retry_preserves_target_and_releases_it_before_the_next_request(self):
        self.options["max_retries"] = 1
        with RequestTargetServer() as server:
            requester = self.requester(server.url)
            response = requester.request("retry-body%1")
            requester.request("next%2")

            self.assertEqual(response.body, b"ok")
            self.assertEqual(server.targets, [b"/retry-body%1", b"/retry-body%1", b"/next%2"])

    def test_pool_connection_retry_preserves_the_explicit_target(self):
        with RequestTargetServer() as server:
            requester = self.requester(server.url)
            adapter = requester.session.get_adapter(server.url)
            adapter.max_retries = Retry(total=1, backoff_factor=0)
            prepared = requester.session.prepare_request(requests.Request("GET", server.url))
            pool = adapter.get_connection_with_tls_context(prepared, verify=False, proxies={})
            make_request = pool._make_request
            attempts = 0

            def fail_once(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ProtocolError("injected connection failure")
                return make_request(*args, **kwargs)

            with patch.object(pool, "_make_request", side_effect=fail_once):
                response = requester.request("retry%1\\*")

            self.assertEqual(response.status, 200)
            self.assertEqual(attempts, 2)
            self.assertEqual(server.targets, [b"/retry%1\\*"])

    def test_pool_status_retry_preserves_the_explicit_target(self):
        with RequestTargetServer() as server:
            requester = self.requester(server.url)
            adapter = requester.session.get_adapter(server.url)
            adapter.max_retries = Retry(total=1, status_forcelist=(503,), backoff_factor=0)
            response = requester.request("retry-status%1")

            self.assertEqual(response.status, 200)
            self.assertEqual(server.targets, [b"/retry-status%1", b"/retry-status%1"])

    def test_shared_pool_keeps_concurrent_request_targets_independent(self):
        self.options["thread_count"] = 2
        with RequestTargetServer() as server:
            requester = self.requester(server.url)
            adapter = requester.session.get_adapter(server.url)
            barrier = threading.Barrier(2, timeout=2)
            errors = []

            def synchronized_headers(_request, **_kwargs):
                barrier.wait()

            def run(path):
                try:
                    self.assertEqual(requester.request(path).status, 200)
                except BaseException as error:
                    errors.append(error)

            workers = [threading.Thread(target=run, args=(path,)) for path in ("first%1", "second%2")]
            with patch.object(adapter, "add_headers", side_effect=synchronized_headers):
                try:
                    for worker in workers:
                        worker.start()
                finally:
                    for worker in workers:
                        worker.join(timeout=4)
                        self.assertFalse(worker.is_alive(), "request worker leaked")

            self.assertEqual(errors, [])
            self.assertCountEqual(server.targets, [b"/first%1", b"/second%2"])

    def test_raw_pool_rejects_redirect_ownership_before_connecting(self):
        pool = PathPreservingHTTPConnectionPool("example.invalid")
        self.addCleanup(pool.close)
        with patch.object(pool, "_get_conn") as get_connection:
            with self.assertRaisesRegex(ValueError, "redirects must be handled by Requests"):
                pool.urlopen("GET", RawRequestTarget("/raw%1"))
        get_connection.assert_not_called()
