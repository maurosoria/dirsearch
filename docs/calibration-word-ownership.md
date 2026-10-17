# Calibration word ownership

`BaseFuzzer` owns one `StealthWordGenerator`: its private RNG and the set of
previously generated words. The controller constructs a new fuzzer for each
active target. Profiles borrow that generator explicitly through
`Scanner(..., word_generator=...)` or `AsyncScanner.create(...)`.

## Lifetime and behavior

- Default, custom-response, prefix, suffix and extension profiles share the
  fuzzer's generator. Initial probes and extra auto-calibration samples use it.
- Rebuilding profiles for another directory on the same target keeps the
  generator and its seen-word history. It is not reset by `setup_scanners()`.
- A new target/fuzzer gets independent randomness and history. Words are no
  longer reserved across unrelated targets or complete runs in the same process.
- A standalone scanner creates its own generator unless one is explicitly
  supplied. A caller can inject a seeded instance for reproducible tests.
- History becomes collectable when the fuzzer and its profiles are released;
  there is no module-global instance or compatibility wrapper retaining it.
  History still grows with calibration on a single target, as needed for its
  existing no-repeat behavior; this is not a bounded-cache change.

The word bank, candidate generation, length/entropy constraints, omit handling,
retry limit, request ordering and sample counts are unchanged. Generator state
is not saved in sessions; resume still rebuilds wildcard profiles. It does not
contain user wordlist entries and is unrelated to `NativeWordlist` ownership.

## Engine boundary

Threaded and native fuzzers use synchronous `Scanner` profiles; the async fuzzer
uses `AsyncScanner`. Each fuzzer calibrates sequentially before dispatching its
directory's scan work. No new shared lock or per-request ownership handoff is
needed. A generator is not intended for concurrent use by multiple fuzzers.

Native calibration already uses the Python profile layer with native HTTP
requests. This change does not move work out of Rust, change `scan_chunks`, or
add work to the fuzzing hot path. It makes no throughput claim.

## Regression coverage

`tests/core/test_calibration_words.py` uses recording requester fixtures to
check ownership in all three fuzzer classes, every profile variant, directory
transitions, deterministic probe paths, interleaved independent async scanners
and history reclamation. These are calibration-boundary tests, not transport
parity tests. The existing generator constraint tests and native/local-server
integration suite remain separate coverage.
