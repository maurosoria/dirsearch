import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase, skipUnless
from unittest.mock import patch
from urllib.parse import urlsplit

from lib.connection.native import NativeHTTPBackend, NativeRequester
from lib.connection.requester import AsyncRequester, Requester
from lib.core.data import options
from lib.core.native_runtime import get_native_extension_version_error
from lib.core.request_config import RequestConfig
from tests.connection.test_native_backend import FakeNativeModule


try:
    import dirsearch_native
except ImportError:
    dirsearch_native = None

NATIVE_AVAILABLE = (
    dirsearch_native is not None
    and get_native_extension_version_error(dirsearch_native) is None
)


class ConfigEchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.connection.settimeout(3)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        target = urlsplit(self.path)
        request_path = target.path + (f"?{target.query}" if target.query else "")
        # Both requests must reach the fixture before either one can complete.
        if request_path.startswith("/parallel?"):
            self.server.request_barrier.wait(timeout=5)
        response = json.dumps({
            "method": self.command,
            "path": request_path,
            "via_proxy": bool(target.netloc),
            "run": self.headers.get("X-Run"),
            "auth": self.headers.get("Authorization"),
            "cookie": self.headers.get("Cookie"),
            "body": body.decode("utf-8"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Set-Cookie", f"run={self.headers['X-Run']}; Path=/")
        self.end_headers()
        self.wfile.write(response)

    do_PUT = do_POST

    def log_message(self, format, *args):
        pass


class TestRequestConfigIsolation(TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ConfigEchoHandler)
        self.server.request_barrier = threading.Barrier(2)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
        )
        self.server_thread.start()
        self.addCleanup(self.stop_server)
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}/"
        self.configs = (
            RequestConfig(
                method="POST", body=b"first-body", headers=(("X-Run", "first"),),
                auth_type="bearer", auth="first-token", timeout=3, max_retries=0,
            ),
            RequestConfig(
                method="PUT", body=b"second-body", headers=(("X-Run", "second"),),
                auth_type="bearer", auth="second-token", timeout=3, max_retries=0,
            ),
        )

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=3)
        self.assertFalse(self.server_thread.is_alive())

    def assert_echo(self, response, index, *, path, cookie, replay=False):
        name = ("first", "second")[index]
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body), {
            "method": ("POST", "PUT")[index],
            "path": f"/{path}?run={name}",
            "via_proxy": replay,
            "run": name,
            "auth": f"Bearer {name}-token",
            "cookie": f"run={name}" if cookie else None,
            "body": f"{name}-body",
        })

    def configure_target(self, requester, index):
        requester.set_url(self.url)
        requester.set_query(f"run={('first', 'second')[index]}")

    def run_sync_pair(self, native=False):
        # An empty global map catches reads during construction, lazy startup,
        # request dispatch and cleanup. Only the explicit configs are available.
        with (
            patch.dict(options, {}, clear=True),
            patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}),
        ):
            requesters = []
            try:
                for index, config in enumerate(self.configs):
                    requester = (
                        NativeRequester(config, filter_options={})
                        if native else Requester(config)
                    )
                    requesters.append(requester)
                    self.configure_target(requester, index)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(r.request, "parallel") for r in requesters]
                    responses = [future.result(timeout=10) for future in futures]
                for index, (requester, response) in enumerate(zip(requesters, responses)):
                    self.assert_echo(response, index, path="parallel", cookie=False)
                    self.assert_echo(
                        requester.request("again"), index, path="again", cookie=True,
                    )
                    self.assert_echo(
                        requester.request("replay", proxy=self.url), index,
                        path="replay", cookie=True, replay=True,
                    )
            finally:
                for requester in requesters:
                    requester.close()

    def test_threaded_requesters_keep_independent_policy_and_cookies(self):
        self.run_sync_pair()

    @skipUnless(NATIVE_AVAILABLE, "matching native extension is not installed")
    def test_native_requesters_keep_independent_policy_and_cookies(self):
        self.run_sync_pair(native=True)

    def test_async_requesters_keep_independent_policy_and_cookies(self):
        async def run():
            requesters = []
            try:
                for index, config in enumerate(self.configs):
                    requester = AsyncRequester(config)
                    requesters.append(requester)
                    self.configure_target(requester, index)
                responses = await asyncio.wait_for(
                    asyncio.gather(*(r.request("parallel") for r in requesters)),
                    timeout=10,
                )
                for index, (requester, response) in enumerate(zip(requesters, responses)):
                    self.assert_echo(response, index, path="parallel", cookie=False)
                    self.assert_echo(
                        await requester.request("again"), index, path="again", cookie=True,
                    )
                    self.assert_echo(
                        await requester.replay_request("replay", self.url), index,
                        path="replay", cookie=True, replay=True,
                    )
            finally:
                for requester in requesters:
                    await requester.close()

        with (
            patch.dict(options, {}, clear=True),
            patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}),
        ):
            asyncio.run(run())


class TestNativeConfigSnapshot(TestCase):
    def test_lazy_engine_replay_and_reopen_keep_the_original_snapshot(self):
        fake_native = FakeNativeModule()
        config = RequestConfig(
            method="PATCH", body=b"original", headers=(("X-Run", "original"),),
            auth_type="bearer", auth="original-token", concurrency=3,
            timeout=2, max_retries=4, max_rate=7, delay=0.1,
            follow_redirects=True, proxies=("http://origin-proxy.example:8080",),
            proxy_auth="proxy-user:proxy-password",
        )
        filters = {"include_status_codes": [200], "match_sizes": [[1, 10]]}
        with patch.dict("sys.modules", {"dirsearch_native": fake_native}):
            requester = NativeRequester(config, filter_options=filters)
            requester.set_url("http://example.test/")
            filters["include_status_codes"].append(404)
            filters["match_sizes"][0][1] = 99
            with patch.dict(options, {}, clear=True):
                try:
                    backend = requester.get_backend()
                    list(backend.scan(requester._url, ["first"]))
                    list(backend.scan(requester._url, ["second"]))
                    self.assertEqual(len(fake_native.engines), 1)
                    requester.request("replay", proxy="http://replay.example:8080")
                    requester.close()
                    requester.request("reopened")
                finally:
                    requester.close()

        self.assertEqual(len(fake_native.engines), 3)
        for engine in fake_native.engines:
            self.assertEqual(engine.config["method"], "PATCH")
            self.assertEqual(engine.config["body"], b"original")
            self.assertIn(("X-Run", "original"), engine.config["headers"])
            self.assertEqual(engine.config["auth_credential"], "original-token")
            self.assertEqual(engine.config["concurrency"], 3)
            self.assertEqual(engine.config["timeout_secs"], 2)
            self.assertEqual(engine.config["max_rate"], 7)
            self.assertEqual(engine.config["delay_secs"], 0.1)
            self.assertTrue(engine.config["follow_redirects"])
            self.assertEqual(engine.calls[0][1]["max_retries"], 4)
        self.assertEqual(fake_native.engines[1].config["proxies"], [
            "http://proxy-user:proxy-password@replay.example:8080",
        ])
        self.assertEqual(
            fake_native.engines[0].config["proxies"],
            fake_native.engines[2].config["proxies"],
        )
        self.assertEqual(fake_native.filter_configs[0].config, {
            "include_status_codes": [200], "match_sizes": [[1, 10]],
        })

    def test_direct_backend_copies_filters_before_lazy_compilation(self):
        fake_native = FakeNativeModule()
        filters = {"filter_sizes": [[5, 10]]}
        with (
            patch.dict("sys.modules", {"dirsearch_native": fake_native}),
            patch.dict(options, {}, clear=True),
        ):
            backend = NativeHTTPBackend(RequestConfig(), filter_options=filters)
            try:
                filters["filter_sizes"][0][1] = 99
                list(backend.scan("http://example.test/", ["first"]))
            finally:
                backend.close()

        self.assertEqual(fake_native.filter_configs[0].config, {"filter_sizes": [[5, 10]]})
