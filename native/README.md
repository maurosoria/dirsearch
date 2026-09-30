# dirsearch native PoC

This crate is an experimental Phase 5 native backend. It is opt-in for source
installs and is included in `native-rust` release artifacts.

It exposes a small PyO3 API:

- `generate_wordlist(...)` for deterministic ordered wordlist generation.
- `generate_wordlist_owned(...)` for keeping native-scan corpora in Rust.
- `NativeHttpEngine` for concurrent HTTP requests using `reqwest` and `tokio`.
- `NativeHttpSession` for explicitly sharing cookies and request-rate state
  across engine rebuilds and replay transports.
- `NativeFilterConfig` for compiling and reusing one immutable filter policy.

The module also exposes `__version__`. The Python request and wordlist
backends require an exact version match so a stale compiled extension fails
with a rebuild instruction instead of silently using an older native contract.

`NativeHttpEngine` keeps its Tokio runtime and HTTP clients alive across
multiple scans and supports cooperative cancellation. Each scan is represented
by one shared Rust job rather than a separate parameter bundle per worker.
Python constructs one immutable filter configuration and reuses it across
scans. `scan(...)` returns every result for calibration and individual backend
requests. `scan_chunks(...)` and `scan_owned_chunks(...)` are the only scanning
path used by `NativeFuzzer`; they deliver ordered chunks and omit Python result
objects for filtered misses. Status-filter misses drain their response stream
for connection reuse without retaining headers or body data. Python still owns
callbacks, session recovery, and dynamically discovered paths. Native regex matching uses the hybrid
`fancy-regex` engine: ordinary expressions retain the finite-automata fast path,
while lookarounds and backreferences run in its bounded backtracking engine.
Basic, Bearer/JWT, Digest, NTLM, and target-embedded Basic origin authentication
are performed inside the native engine. Challenge responses stay scoped to the
original origin, including when redirects are enabled. Digest challenges are
cached per origin for later requests. NTLM uses one HTTP/1.1 client per worker
and proxy so each Type 1/2/3 exchange stays on one connection; HTTPS exchanges
also send the RFC 5929 `tls-server-end-point` channel binding and fail closed if
the peer certificate cannot produce it. Digest and NTLM cannot be combined
with byte-preserving raw HTTP targets, so those combinations fail explicitly
instead of silently sending unauthenticated requests.

`--max-rate` uses one session-wide sliding window, so concurrent workers,
engine rebuilds, and replay requests all consume the same budget. Retries stay
inside their original logical request and do not consume another rate slot.
`--delay` keeps an independent deadline for each worker and carries that
deadline across scan boundaries. Both waits are asynchronous and remain
interruptible by pause, quit, and scan cancellation.

Native fuzzer results are returned incrementally through ordered chunks.
Rust reorders concurrent completions, omits per-response Python objects for
filtered misses, and records progress in a fixed-size atomic bitmap while
Python runs callbacks. Only actionable results enter the shared result map, and
both structures are bounded by the active native-wordlist claim. A ready ordered
prefix is capped at 2048 completed paths, and the coordinator checks for a
smaller prefix every 20 ms. That interval is a flush
target rather than a hard latency guarantee: an earlier slow request can delay
later completions until they form a releasable prefix. Python releases only the
delivered prefix of its dictionary claim, so checkpoints remain portable
between the threaded, async, and native engines. Cancellation or callback
failure leaves the undelivered suffix available for a later resume.

## Request state and ownership

The native request path separates state by lifetime. This keeps the Python/Rust
boundary small and makes it clear which changes require rebuilding an engine:

| Owner | Lifetime | Responsibility |
| --- | --- | --- |
| `NativeHttpEngine` | Python backend instance | Owns the Tokio runtime, concurrency limit, cancellation handle, and one request context. |
| `NativeHttpSession` | Requester lifetime | Shares the cookie jar and request-rate window with rebuilt origin engines and replay transports. |
| `NativeRequestContext` | Engine lifetime | Reuses built clients, raw headers, method/body, transport flags, per-worker delay deadlines, and the session handle across scans. |
| `ScanJob` | One engine scan call | Carries paths, base URL, query, filter and retry policy, and body limit from the PyO3 boundary to the scheduler. |
| `ScanTask` | One active worker set | Adds the cancellation handle, result-delivery policy, and atomic counter used by workers to claim paths. |
| `ClientRequest` / `RawHttpRequest` | One target, including retries | Borrows the request inputs needed by the selected transport and returns one native result. |

The ownership flow is:

```text
Python NativeHTTPBackend
  -> NativeHttpEngine
       -> Arc<NativeRequestContext>       (reused across scans)
       -> ScanJob                         (one call from Python)
            -> Arc<ScanTask>              (shared by bounded workers)
            -> ClientRequest/RawHttpRequest (one claimed target)
```

Put a value in `NativeRequestContext` when it is fixed by engine construction
and reused by every scan. Put it in `ScanJob` when Python supplies it for one
call. Put worker coordination in `ScanTask`, and transport-only values in the
request for one claimed target.
Session state is the deliberate exception to immutability: the context holds a
stable `NativeHttpSession` handle so all clients and replay engines can update
the same policy-controlled cookie jar and request-rate window.

## Source layout

`src/lib.rs` only registers the Python module. The implementation is split by
responsibility:

- `engine.rs` owns the PyO3 API, persistent runtime, client construction, and
  cancellation handle.
- `scan.rs` owns per-scan jobs, bounded workers, cancellation cleanup, and the
  choice between complete collection and incremental chunks.
- `chunks.rs` reorders concurrent completions and builds compact, ordered
  chunks for Python-owned callbacks and checkpoints.
- `session.rs` owns explicit cross-engine session state and cookie policy.
- `pacing.rs` owns the shared request-rate limiter and per-worker delay lanes.
- `request_target.rs` owns query insertion and URL quoting before scheduling.
- `ntlm.rs` owns NTLMv2 token generation and TLS channel-binding derivation.
- `transport.rs` owns reqwest requests and streamed response decoding.
- `raw_client.rs` selects and drives the byte-preserving HTTP adapter, while
  `raw_http.rs` implements HTTP/1.1 framing and parsing.
- `filters.rs`, `result.rs`, and `wordlist.rs` contain their corresponding
  domain logic without depending on the PyO3 module entrypoint.
- `tests.rs` contains cross-module native regression tests.

Build the native engine from an installed dirsearch package with Python 3.14,
Rust 1.88 or newer, Python development headers, and a C compiler:

```sh
dirsearch-build-native
```

For development from a source checkout, use the repository helper:

```sh
python3.14 scripts/build_native.py --out dist/native-wheels
```

Both helpers install the exact built wheel and verify `import dirsearch_native`.
Release-equivalent native wheels target Python 3.14 and PyO3's `cp313-abi3`
stable ABI. `maturin` is pulled by pip/build scripts from `native/pyproject.toml`.

The benchmark summary for this backend is in
[`docs/native-backend-benchmarks.md`](../docs/native-backend-benchmarks.md).

You can use the native scan path with the default GET method:

```sh
python3 dirsearch.py -u https://target -w db/dicc.txt --request-backend native
```

Native request pacing uses the same CLI options as the Python engines:

```sh
python3 dirsearch.py -u https://target -w db/dicc.txt \
  --request-backend native --max-rate 50 --delay 0.05
```

Other HTTP methods and request bodies use the same CLI options as the Python
backends. `--data-file` preserves the file bytes without decoding or newline
conversion:

```sh
python3 dirsearch.py -u https://target -w db/dicc.txt \
  --request-backend native --http-method POST --data-file request-body.bin
```

Client certificate authentication is also applied inside the Rust HTTP client.
Pass separate PEM certificate and unencrypted private-key files with
`--cert-file` and `--key-file`; the two options must be used together.

`--random-agent` selects a request-local User-Agent for every attempt,
including retries, without mutating headers shared by concurrent workers.
