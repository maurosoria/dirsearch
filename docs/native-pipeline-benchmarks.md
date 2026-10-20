# Native classification and calibration benchmarks

This series follows the content normalization and similarity acceleration.
It aligns response text semantics, profiles the remaining Python work, moves
eligible wildcard comparisons to native workers, and accelerates calibration.

The pull requests remain separate and depend on each other in this order:

1. #1762: content normalization and similarity.
2. #1763: response text parity.
3. #1764: response-stage profiling.
4. #1765: native wildcard classification and ASCII similarity positions.
5. #1766: stable calibration patterns and bounded first-probe concurrency.

## Method

Compare complete fresh CLI processes on the same controlled target, including
startup, wildcard calibration, wordlist scanning and JSON reporting. Each cell
has one unmeasured full scan per variant followed by three measured scans;
variant order is shuffled for every repeat. Report medians of wordlist entries
divided by complete process wall time. Calibration requests are counted
separately and their time remains included.

Use Python 3.14.5 and Rust 1.88.0 on Linux x86_64 with dedicated CPUs. HTTP
concurrency is 40 except the 20 ms case, which uses 100. Native runtime workers
follow available CPUs rather than HTTP concurrency. All variants use the Python
wordlist backend, no explicit status exclusions and no retries, crawl or
recursion. Network-delay cases add deterministic delay per request.

The target verifies the complete wordlist path set, request count and absence
of duplicates. JSON reports must contain exactly the expected finding paths;
checksums compare full sets, not only counts. Large positive corpora exercise
response conversion, callbacks and reporting as well as negative classification.

## Results

<!-- The measured median table is generated from the completed validation matrix. -->

Static rows return identical negative bodies. Dynamic HTML/JSON rows vary paths,
tokens or identifiers inside a negative template and retain five control
findings. The same-status control uses distinct positive JSON with the same HTTP
status as the soft-404 profile. The all-positive 404 HTML case also preserves
status and content type with comparable body length while returning different documents.
All-positive HTML and binary rows retain every requested path. The two-entry
150 ms case retains one finding and primarily measures preparation cost.

Direct HTTP client rates and CPU replay are different measurements and must not
be compared with these end-to-end rates. Earlier benchmark tables used different
builds and corpora; compare variants within this matrix.

## Correctness and release checks

Response decoding uses one charset/text policy across engines. Non-ASCII,
binary, incomplete, redirect and unsupported filter cases keep the Python path
when native classification cannot preserve its semantics. Native and Python
fallback responses share ordered calibration observations; duplicate-result
filtering remains separate. The native extension requires rebuilding.

Validation includes the complete Python test suite with the matching extension,
Python 3.11 without the extension, Rust release tests, formatting and Clippy,
exact normalization/similarity comparisons, calibrated-pattern parity and
packaged source checks. Compose-generated Bake builds with host networking
cover threaded, async and native-rust images, including version/help and
controlled scan checks. Benchmark and release validation artifacts remain
outside the repository.
