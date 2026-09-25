# dirsearch native PoC

This crate is an experimental Phase 5 native backend. It is opt-in for source
installs and is included in `native-rust` release artifacts.

It exposes a small PyO3 API:

- `generate_wordlist(...)` for deterministic ordered wordlist generation.
- `generate_wordlist_owned(...)` for keeping native-scan corpora in Rust.
- `NativeHttpEngine` for batch HTTP requests using `reqwest` and `tokio`.
- `NativeHttpSession` for explicitly sharing cookie state across engine rebuilds
  and replay transports.
- `NativeFilterConfig` for compiling and reusing one immutable filter policy.
- `scan_http(...)` as the compatibility entrypoint backed by a cached engine.

The module also exposes `__version__`. The Python request and wordlist
backends require an exact version match so a stale compiled extension fails
with a rebuild instruction instead of silently using an older native contract.

`NativeHttpEngine` keeps its Tokio runtime and HTTP clients alive across
multiple batches and supports cooperative cancellation. Each batch is represented
by one shared Rust scan task rather than a separate parameter bundle per worker.
Python constructs one
immutable filter configuration and reuses it across those batches. The
`scan(...)` and `scan_owned_batch(...)` methods evaluate the cheap legacy
status/size filters and advanced match/filter options in native code. Compact
status-filter misses drain their response stream for connection reuse without
retaining headers or body data. Python still owns callbacks, session recovery,
and dynamically discovered paths. Native regex matching uses the hybrid
`fancy-regex` engine: ordinary expressions retain the finite-automata fast path,
while lookarounds and backreferences run in its bounded backtracking engine.
Basic, Bearer/JWT, Digest, and target-embedded Basic origin authentication are
performed inside the native engine. Digest challenge responses stay scoped to
the original origin, including when redirects are enabled, and are cached per
origin for later requests. Digest cannot be combined with byte-preserving raw
HTTP targets, so that combination fails explicitly instead of silently sending
an unauthenticated request. NTLM remains an explicit parse-time error because
the native transport cannot yet guarantee both HTTPS channel binding and
connection affinity under concurrent scans.

## Request state and ownership

The native request path separates state by lifetime. This keeps the Python/Rust
boundary small and makes it clear which changes require rebuilding an engine:

| Owner | Lifetime | Responsibility |
| --- | --- | --- |
| `NativeHttpEngine` | Python backend instance | Owns the Tokio runtime, concurrency limit, cancellation handle, and one request context. |
| `NativeRequestContext` | Engine lifetime | Reuses built clients, raw headers, method/body, transport flags, and the session handle across batches. Its configuration is immutable; the shared session cookie jar uses internal locking. |
| `ScanTask` | One `scan` or `scan_owned_batch` call | Holds paths, base URL, filter and retry policy, body limit, cancellation handle, and the atomic counter used by workers to claim paths. |
| `ClientRequest` / `RawHttpRequest` | One target, including retries | Borrows the request inputs needed by the selected transport and returns one native result. |

The ownership flow is:

```text
Python NativeHTTPBackend
  -> NativeHttpEngine
       -> Arc<NativeRequestContext>       (reused across batches)
       -> Arc<ScanTask>                   (shared by bounded workers)
            -> ClientRequest/RawHttpRequest (one claimed target)
```

Put a value in `NativeRequestContext` when it is fixed by engine construction
and reused by every batch. Put it in `ScanTask` when Python supplies it for one
batch. Put it in a transport request when it applies to one claimed target.
Cookie contents are the deliberate exception to immutability: the context holds
a stable `NativeHttpSession` handle so all clients and replay engines can update
the same policy-controlled jar.

## Source layout

`src/lib.rs` only registers the Python module. The implementation is split by
responsibility:

- `engine.rs` owns the persistent engine, immutable request context, per-batch
  scan task, bounded scheduler, and cancellation.
- `session.rs` owns explicit cross-engine session state and cookie policy.
- `request_target.rs` owns query insertion and URL quoting before scheduling.
- `transport.rs` owns reqwest requests and streamed response decoding.
- `raw_client.rs` selects and drives the byte-preserving HTTP adapter, while
  `raw_http.rs` implements HTTP/1.1 framing and parsing.
- `filters.rs`, `result.rs`, and `wordlist.rs` contain their corresponding
  domain logic without depending on the PyO3 module entrypoint.
- `tests.rs` contains cross-module native regression tests.

Build the native engine from an installed dirsearch package with Python 3.14,
Rust 1.86 or newer, Python development headers, and a C compiler:

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
