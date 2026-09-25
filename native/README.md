# dirsearch native PoC

This crate is an experimental Phase 5 native backend. It is opt-in for source
installs and is included in `native-rust` release artifacts.

It exposes a small PyO3 API:

- `generate_wordlist(...)` for deterministic ordered wordlist generation.
- `generate_wordlist_owned(...)` for keeping native-scan corpora in Rust.
- `NativeHttpEngine` for batch HTTP requests using `reqwest` and `tokio`.
- `NativeFilterConfig` for compiling and reusing one immutable filter policy.
- `scan_http(...)` as the compatibility entrypoint backed by a cached engine.

The module also exposes `__version__`. The Python request and wordlist
backends require an exact version match so a stale compiled extension fails
with a rebuild instruction instead of silently using an older native contract.

`NativeHttpEngine` keeps its Tokio runtime and HTTP clients alive across
multiple batches and supports cooperative cancellation. Python constructs one
immutable filter configuration and reuses it across those batches. The
`scan(...)` and `scan_owned_batch(...)` methods evaluate the cheap legacy
status/size filters and advanced match/filter options in native code. Compact
status-filter misses drain their response stream for connection reuse without
retaining headers or body data. Python still owns callbacks, session recovery,
and dynamically discovered paths. Native regex matching uses the hybrid
`fancy-regex` engine: ordinary expressions retain the finite-automata fast path,
while lookarounds and backreferences run in its bounded backtracking engine.

## Source layout

`src/lib.rs` only registers the Python module. The implementation is split by
responsibility:

- `engine.rs` owns the persistent engine, bounded scheduler, and cancellation.
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
