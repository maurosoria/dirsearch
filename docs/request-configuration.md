# Request configuration ownership

`RequestConfig` is the immutable transport policy for one run. `Controller.run()`
creates it after `setup()` has parsed a raw request or `_import()` has restored a
session, then passes it explicitly to the selected requester. Its adapter accepts
a supplied mapping; it never imports the process-wide options dictionary.

| Responsibility | Owner |
| --- | --- |
| Translate normalized CLI/session options | `RequestConfig.from_options()` at the controller boundary |
| Method, body, headers, configured auth, proxies, TLS files, timeout, retries and pacing | Frozen `RequestConfig` |
| Target URL/query, target auth, cookies, IP overrides and connection pools | Each requester and its session |
| Matching policy | Separate immutable `FilterConfig`, shared with Python filtering |
| Session persistence and response destinations | Existing Python controller and report adapters |

The transport migration replaces direct `options` reads in
`lib/connection/requester.py` and `lib/connection/native.py`. Filter policy is
deliberately not part of `RequestConfig`; its ownership is described in
[filter configuration](filter-configuration.md). Controller discovery policy and
calibration variants now use [DiscoveryConfig](discovery-configuration.md).
Wordlist generation and validation now use
[WordlistConfig](wordlist-configuration.md). Engine selection, fuzzer
concurrency/pacing and stop policy use [ExecutionConfig](execution-configuration.md),
built from the same normalized input as the transport.
[ReportConfig](report-configuration.md) owns report destinations and SQLite
batch policy. Logging and remaining controller globals are separate migration
steps. These snapshots do not yet
make two complete `Controller` instances safe to run together.

## Constructing a requester

```python
from lib.connection.requester import Requester
from lib.core.request_config import RequestConfig

config = RequestConfig(
    method="POST",
    body=b"example=value",
    headers=(("Content-Type", "application/x-www-form-urlencoded"),),
    timeout=3,
    max_retries=0,
)
requester = Requester(config)
try:
    requester.set_url("http://127.0.0.1:8080/")
    response = requester.request("example")
finally:
    requester.close()
```

`AsyncRequester` takes the same config and has asynchronous request/close methods.
`NativeRequester` additionally requires `filter_config`; pass `FilterConfig()`
when no explicit filters are wanted, or use
`FilterConfig.from_options(normalized_options)` at the orchestration boundary.
The optional extension is still loaded lazily.

Headers and proxies are immutable tuples, and mutable byte buffers are copied.
Text bodies stay text so each transport retains its existing encoding behavior.
The normal CLI validation still owns input validation; this object is not a new
CLI parser. Secret-bearing fields are omitted from its representation.
The snapshot freezes option values. Existing environment-proxy behavior and
loading certificate or User-Agent files still belong to the transports.

To change run policy, construct a new config (or use `dataclasses.replace`) and
create a new requester. Do not replace `requester.config` on a live requester:
its existing connection pools were built from the original policy. Explicit
target changes continue through `set_url`, `set_query`, `set_ip`, `set_auth` and
`reset_auth`. Resetting authentication restores the configured baseline.

## Replay, calibration and native execution

Calibration uses the already-configured requester. Replay uses its snapshot and
target authentication while preserving the existing proxy and cookie behavior.
Native engine creation, target-auth/IP rebuilds, chunks and requester reopening
all use the same snapshot. Request policy adds no Python/Rust call per request;
Rust still owns the native execution loop. This is an ownership guarantee, not
a throughput benchmark.

Sessions continue to store their existing options representation. The immutable
object is rebuilt on resume, so this change does not introduce a session schema
migration or tie saved sessions to an engine.

## Regression coverage

`tests/core/test_request_config.py` covers snapshots, nested collection copies,
body types, output capture policy and representations. The connection tests run
two requesters concurrently against a loopback echo fixture for each engine and
verify method, body, headers, auth, query and cookie isolation with the global
options map empty. Native unit coverage also checks lazy compilation, replay,
engine reuse and reopening. Controller tests check construction after both
preparation paths; the existing backend CLI contract covers the production flow.

Run the canonical suite with `python -m unittest discover -s tests -t .`.
Native integration requires Python 3.14 and a matching extension; those cases
skip when the extension is unavailable.
