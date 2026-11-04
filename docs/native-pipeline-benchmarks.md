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
| Native classification | `26b00e7` | 0.2.24 |
| Native calibration | `27a5064` | 0.2.25 |

| Corpus | Entries | Threads | Delay | Previous RPS | Final RPS | Ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static 404, 896 B | 20,005 | 40 | 0 ms | 11,623 | 13,153 | 1.13x |
| Static 404, 896 B | 100,000 | 40 | 0 ms | 16,037 | 17,588 | 1.10x |
| Reflected HTML, ~4 KiB | 6,005 | 40 | 0 ms | 4,916 | 5,616 | 1.14x |
| Token HTML, ~4 KiB | 6,005 | 40 | 0 ms | 4,721 | 5,357 | 1.13x |
| Variable HTML, ~4 KiB | 6,005 | 40 | 0 ms | 3,488 | 5,608 | 1.61x |
| Compact JSON, ~4 KiB | 6,005 | 40 | 0 ms | 2,426 | 4,546 | 1.87x |
| Compact JSON, ~64 KiB | 505 | 40 | 0 ms | 175.7 | 520.3 | 2.96x |
| Reflected HTML, ~64 KiB | 505 | 40 | 0 ms | 494.2 | 581.0 | 1.18x |
| Repeated-path HTML, ~64 KiB | 129 | 40 | 0 ms | 52.1 | 120.6 | 2.31x |
| Same-status JSON controls, ~4 KiB | 6,005 | 40 | 0 ms | 2,427 | 4,546 | 1.87x |
| Unicode UTF-8 HTML, ~4 KiB | 6,005 | 40 | 0 ms | 1,388 | 1,387 | 1.00x |
| Latin-1 HTML, ~4 KiB | 6,005 | 40 | 0 ms | 1,205 | 1,171 | 0.97x |
| All-positive HTML, ~16 KiB | 1,205 | 40 | 0 ms | 1,126 | 1,564 | 1.39x |
| All-positive 404 HTML, ~4 KiB | 6,005 | 40 | 0 ms | 2,362 | 3,123 | 1.32x |
| All-positive binary 404, 64 KiB | 405 | 40 | 0 ms | 494.4 | 494.5 | 1.00x |
| Token HTML, ~4 KiB | 6,005 | 100 | 20 ms | 2,822 | 2,966 | 1.05x |
| Token HTML, ~4 KiB | 2 | 40 | 150 ms | 0.94 | 1.20 | 1.27x |

The previous and final columns compare extension 0.2.22 with 0.2.25. Compact JSON
improves by 87% at 4 KiB and 2.96x at 64 KiB; the all-positive 404 HTML row improves
by 32%. Unicode and binary fallback medians remain approximately flat. Latin-1
is 3% lower in this matrix; the raw samples retain the measured ranges.
These are complete-process rates, including calibration costs.

The intermediate cohorts separate classification from calibration work:

| Corpus | Content 0.2.22 | Parity 0.2.23 | Classification 0.2.24 | Calibration 0.2.25 |
| --- | ---: | ---: | ---: | ---: |
| Static 404, 896 B | 16,037 | 16,038 | 17,596 | 17,588 |
| Compact JSON, ~4 KiB | 2,426 | 2,428 | 4,545 | 4,546 |
| Compact JSON, ~64 KiB | 175.7 | 175.7 | 311.8 | 520.3 |
| Repeated-path HTML, ~64 KiB | 52.1 | 53.2 | 53.2 | 120.6 |
| All-positive HTML, ~16 KiB | 1,126 | 1,180 | 1,562 | 1,564 |
| All-positive 404 HTML, ~4 KiB | 2,362 | 2,642 | 3,124 | 3,123 |
| All-positive binary 404, 64 KiB | 494.4 | 494.6 | 494.8 | 494.5 |

Static rows return identical negative bodies. Dynamic HTML/JSON rows vary paths,
tokens or identifiers inside a negative template and retain five control
findings. The same-status control uses distinct positive JSON with the same HTTP
status as the soft-404 profile. The all-positive 404 HTML case includes 6,000
distinct 404 documents with the same content type and comparable body length, plus five control findings.
All-positive HTML and binary rows retain every requested path. The two-entry
150 ms case retains one finding and primarily measures preparation cost.

Direct HTTP client rates and CPU replay are different measurements and must not
be compared with these end-to-end rates. Earlier benchmark tables used different
builds and corpora; compare variants within this matrix.

## Native wordlist comparison

A separate experiment compares the final 0.2.25 build with Python and native
wordlist readers, using `--wordlist-backend python` and `--wordlist-backend native`.
Each reader has one full warmup and three measured fresh processes per case at
40 HTTP requests in flight. These 12 measured native scans retain exactly the
same five findings, complete path sets and request counts.

| Corpus | Entries | Python wordlist RPS | Native wordlist RPS | Ratio |
| --- | ---: | ---: | ---: | ---: |
| Static 404, 896 B | 100,000 | 17,586 | 23,091 | 1.31x |
| Compact JSON, ~4 KiB | 6,005 | 4,548 | 4,918 | 1.08x |

These rates include preparation and reporting. Keep this comparison separate
from the four-cohort matrix, where every build uses the Python wordlist reader.

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

The matching Python 3.14/native suite runs 1,165 tests with four skips, and the
Rust release suite passes 100 tests with formatting and Clippy checks. The
function audit completes 163,399 normalization, similarity and parser comparisons
without differences. Additional tests cover exact calibrated-pattern parity,
shared native/fallback state, isolated surrogate text and positive-decision reuse. Source-file and wheel
checksums verify every timed cohort against its recorded artifacts.

Release validation covers Python 3.11 without the extension, Python 3.14 native
and packaged Rust sources. Compose-generated Bake builds with host networking
cover threaded, async and native-rust images, including version/help and
controlled scan checks. Benchmark and release validation artifacts remain
outside the repository. Cargo audit continues to report seven inherited
advisories in unchanged dependency versions; this series does not resolve them.
