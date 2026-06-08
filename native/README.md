# dirsearch native PoC

This crate is an experimental Phase 5 native backend. It is opt-in for source
installs and is included in `native-rust` release artifacts.

It exposes two PyO3 functions:

- `generate_wordlist(...)` for deterministic ordered wordlist generation.
- `scan_http(...)` for batch HTTP GET requests using `reqwest` and `tokio`.

`scan_http(...)` also evaluates the cheap legacy status/size filters and the
advanced match/filter options in native code. Filtered responses are returned as
lightweight events with metadata and an empty body so Python can keep progress
and not-found callbacks authoritative. Native regex matching uses Rust's
`regex` crate; patterns unsupported by that engine fail before the scan starts.
The native request path honors dirsearch concurrency, delay, retry, timeout, and
max-rate controls.

Build the native engine from an installed dirsearch package with Python 3.14,
Rust/Cargo, Python development headers, and a C compiler:

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

You can use the native scan path in dirsearch with supported GET scans:

```sh
python3 dirsearch.py -u https://target -w db/dicc.txt --request-backend native
```
