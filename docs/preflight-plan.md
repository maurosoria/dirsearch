# Preflight Scanner Calibration Plan

## Summary

Add an opt-in `--preflight` mode that calibrates each target before scanning.
The preflight reuses dirsearch wildcard scanners to detect burst-only response
marks, chooses a safer thread/delay profile, records CDN/WAF-like fingerprints,
and then runs the normal scan. During scans, a streak of 8 accepted matches
triggers a lightweight recalibration check so future repeated false positives
can be filtered without removing already emitted results.

## Phases

1. Add CLI/config/API surface:
   - `--preflight`
   - `preflight = False`
   - `FuzzerConfig(preflight=False)`
   - `PreflightResult` for applied profile, fingerprints, observations, and
     recalibration events.
2. Add fingerprinting:
   - Detect conservative header signals for Cloudflare and Akamai.
   - Preserve header evidence and behavior tags for future provider wordlists.
   - Keep fingerprinting informational in v1; it must not decide filtering by
     itself.
3. Add scanner-based preflight:
   - Build the same default, dotted/prefix, suffix, and extension scanner
     profiles used by normal fuzzers.
   - Probe mixed stealth Markov paths and a small sample of wordlist paths
     without consuming the main dictionary.
   - Try a fixed thread/delay ladder and select the first clean profile.
   - If no clean profile exists, apply the most conservative profile.
4. Add runtime recalibration:
   - Track consecutive accepted matches.
   - At 8 consecutive matches, run a lightweight repeated-fingerprint check.
   - If confirmed, mark future matching responses as runtime-calibrated noise.
   - Do not delete or rewrite reports for results already emitted.
5. Support all stacks:
   - Python sync.
   - Python async.
   - Native Rust request backend, including delay support in native bursts.

## Acceptance Tests

- Python sync preflight detects burst-only scanner marks and applies safer
  threads/delay.
- Python async uses the same scanner decision model.
- Native Rust supports calibrated delay/thread profiles.
- Recalibration filters future repeated false-positive matches after 8 accepted
  matches.
- Preflight does not consume the main wordlist index.
- Fingerprint reports conservative Cloudflare/Akamai header evidence.

## Validation Commands

```sh
python3 -m unittest tests.core.test_preflight tests.core.test_fingerprint
python3 -m unittest tests.core.test_importable_api tests.core.test_scanner
python3 -m unittest tests.connection.test_native_backend tests.core.test_native_fuzzer
python3 testing.py
cargo test --manifest-path native/Cargo.toml
```
