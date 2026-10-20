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

The matrix contains 204 measured scans, 68 complete warmups and 2,121,612
measured wordlist requests. All variants preserve the expected request-path and
finding sets, with no duplicate wordlist requests and identical calibration
probe counts within each cell.

| Cohort | Commit | Extension |
| --- | --- | --- |
| Content acceleration | `0adee4c` | 0.2.22 |
| Text parity | `cd3b9b1` | 0.2.23 |
| Native classification | `ef5562b` | 0.2.24 |
| Native calibration | `b7b8582` | 0.2.25 |

| Corpus | Entries | Threads | Delay | Previous RPS | Final RPS | Ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static 404, 896 B | 20,005 | 40 | 0 ms | 11,963 | 13,154 | 1.10x |
| Static 404, 896 B | 100,000 | 40 | 0 ms | 16,167 | 17,596 | 1.09x |
| Reflected HTML, ~4 KiB | 6,005 | 40 | 0 ms | 4,922 | 5,614 | 1.14x |
| Token HTML, ~4 KiB | 6,005 | 40 | 0 ms | 4,914 | 5,361 | 1.09x |
| Variable HTML, ~4 KiB | 6,005 | 40 | 0 ms | 3,486 | 5,614 | 1.61x |
| Compact JSON, ~4 KiB | 6,005 | 40 | 0 ms | 2,425 | 4,377 | 1.80x |
| Compact JSON, ~64 KiB | 505 | 40 | 0 ms | 175.7 | 495.8 | 2.82x |
| Reflected HTML, ~64 KiB | 505 | 40 | 0 ms | 495.2 | 548.9 | 1.11x |
| Repeated-path HTML, ~64 KiB | 129 | 40 | 0 ms | 53.3 | 120.7 | 2.27x |
| Same-status JSON controls, ~4 KiB | 6,005 | 40 | 0 ms | 2,475 | 4,382 | 1.77x |
| Unicode UTF-8 HTML, ~4 KiB | 6,005 | 40 | 0 ms | 1,387 | 1,370 | 0.99x |
| Latin-1 HTML, ~4 KiB | 6,005 | 40 | 0 ms | 1,194 | 1,205 | 1.01x |
| All-positive HTML, ~16 KiB | 1,205 | 40 | 0 ms | 1,127 | 1,566 | 1.39x |
| All-positive 404 HTML, ~4 KiB | 6,005 | 40 | 0 ms | 2,640 | 3,119 | 1.18x |
| All-positive binary 404, 64 KiB | 405 | 40 | 0 ms | 494.4 | 494.3 | 1.00x |
| Token HTML, ~4 KiB | 6,005 | 100 | 20 ms | 2,895 | 2,968 | 1.03x |
| Token HTML, ~4 KiB | 2 | 40 | 150 ms | 0.94 | 1.20 | 1.27x |

The previous and final columns compare extension 0.2.22 with 0.2.25. Compact JSON
improves by 80% at 4 KiB and 2.82x at 64 KiB; the all-positive 404 HTML row improves
by 18%. Unicode, Latin-1 and binary fallback rows remain approximately flat.
These are complete-process rates, including calibration costs.

The intermediate cohorts separate classification from calibration work:

| Corpus | Content 0.2.22 | Parity 0.2.23 | Classification 0.2.24 | Calibration 0.2.25 |
| --- | ---: | ---: | ---: | ---: |
| Static 404, 896 B | 16,167 | 16,037 | 17,439 | 17,596 |
| Compact JSON, ~4 KiB | 2,425 | 2,427 | 4,382 | 4,377 |
| Compact JSON, ~64 KiB | 175.7 | 178.7 | 311.7 | 495.8 |
| Repeated-path HTML, ~64 KiB | 53.3 | 53.2 | 53.1 | 120.7 |
| All-positive HTML, ~16 KiB | 1,127 | 1,126 | 1,471 | 1,566 |
| All-positive 404 HTML, ~4 KiB | 2,640 | 2,698 | 3,201 | 3,119 |
| All-positive binary 404, 64 KiB | 494.4 | 493.6 | 494.1 | 494.3 |


Static rows return identical negative bodies. Dynamic HTML/JSON rows vary paths,
tokens or identifiers inside a negative template and retain five control
findings. The same-status control uses distinct positive JSON with the same HTTP
status as the soft-404 profile. The all-positive 404 HTML case includes 6,000 distinct 404 documents with
the same content type and comparable body length, plus five control findings.
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

Concurrent first probes can reach the server in a different order. Existing
authentication/cookie guards preserve sequential preparation for known session
state; the throughput corpus uses controlled stateless targets. These checks do
not establish equivalence for arbitrary request-order-dependent applications.

The matching Python 3.14/native suite runs 1,163 tests with four skips, and the
Rust release suite passes 100 tests with formatting and Clippy checks. The
function audit completes 163,399 normalization, similarity and parser comparisons
without differences. Additional tests cover exact calibrated-pattern parity,
shared native/fallback state and positive-decision reuse. Source-file and wheel
checksums verify every timed cohort against its recorded artifacts.

Release validation covers Python 3.11 without the extension, Python 3.14 native
and packaged Rust sources. Compose-generated Bake builds with host networking
cover threaded, async and native-rust images, including version/help and
controlled scan checks. Benchmark and release validation artifacts remain
outside the repository. Cargo audit continues to report seven inherited
advisories in unchanged dependency versions; this series does not resolve them.
