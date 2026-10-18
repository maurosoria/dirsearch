# Request-target ownership

The threaded requester preserves already-quoted targets without thread-local
state. The normal URL is still used for routing, TLS, cookies and authentication;
the exact HTTP request target is a separate value carried by that request.
No target is assigned to a pool, a connection or a process-global context.

## Transport boundary

1. `Requester` prepares headers/body/authentication normally, then assigns a
   `RequestTargetURL(url, request_target)` to `PreparedRequest.url`. The string
   subclass satisfies Requests' URL contract while exposing an explicit target
   property; no extra attributes are attached to third-party request objects.
2. The socket-options adapter selects the wire form using Requests' routing
   decision: origin form for direct, SOCKS and CONNECT-tunneled requests;
   absolute form for forwarding HTTP proxies. It returns a `RawRequestTarget`
   string marker so ordinary requests are not opted into raw handling.
3. `PathPreservingPoolMixin.urlopen()` passes that value as the explicit
   `request_target` argument through urllib3. urllib3 may normalize its routing
   URL, but keeps the separate argument across connection and status retries.
4. `_make_request()` consumes the argument and restores the exact target before
   the normal connection implementation writes it. The argument is not a header
   and is not forwarded into response constructors or connection configuration.

The two string types serve different boundaries: a logical URL with its
origin-form target versus the adapter's final wire target. They avoid copying
Requests' adapter implementation or storing per-request data on shared handles.
IP override connections still own only routing behavior. SOCKS pools reuse the
upstream connection classes because target preservation now happens at the pool.

## Copies, redirects and failures

Requests copies its URL unchanged for authentication retries, preserving the
target for Digest/NTLM's copied requests. Redirect resolution replaces the URL,
so a new hop does not inherit the initial target. Redirect URL normalization is
unchanged; this does not promise byte-preserving redirect locations.

Requests owns redirect handling (`HTTPAdapter` calls urllib3 with
`redirect=False`). Raw-target pool calls that instead request urllib3-owned
redirects fail before acquiring a connection. This prevents a retry argument
from accidentally following a redirect. Ordinary, unmarked pool requests retain
urllib3's normal behavior.

Nested requests, failures and reused sockets need no target cleanup: there is
no ambient value to restore or delete. Other requests cannot borrow a target
merely because they run on the same thread or use the same pool.

## Scope and validation

Async requests retain their existing request-extension boundary and use the
same target-joining helper. Rust transport code, native chunks, request pacing,
session formats and public CLI/API entrypoints are unchanged. This does not add
raw HTTPS support to the native fallback or establish complete controller
concurrency safety.

Tests capture request-line bytes for malformed escapes, nested requests,
unmarked requests, redirects, Digest authentication, body/connection/status
retries, concurrent shared-pool calls and keep-alive socket reuse. Local proxy
contracts also cover nested targets over direct HTTP/TLS, HTTP/HTTPS forwarding
or CONNECT, and SOCKS. All new worker/socket waits are bounded, and fixture
shutdown checks that server threads terminate.

Run:

```sh
python -m unittest tests.connection.test_request_target_ownership tests.connection.test_requester tests.connection.test_proxy_integration
python -m unittest discover -s tests -t .
```

Setuptools package discovery and PyInstaller's existing
`collect_submodules('lib')` include `lib/connection/request_target.py`. The
installed-package check exercises the carrier and adapter together.
