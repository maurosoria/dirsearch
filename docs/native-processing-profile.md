# Native response processing profile

Local instrumentation measured Python thread CPU in normalization, similarity,
pattern comparison, calibration, response construction, filters and dispatch.
Exclusive time subtracts nested stages; inclusive percentages must not be added
together. Temporary instrumentation and raw output stay outside version control.

Run the same controlled corpus separately without instrumentation to measure
full CLI RPS. Include process startup, wildcard calibration and reports; use at
least three repeats and report medians. Keep HTTP client-only measurements and
CPU replay distinct from full scan throughput.

The regression matrix should contain exact static negatives, reflected paths,
changing tokens, compact JSON, shared layouts, large bodies, genuinely distinct
positive responses, Unicode, binary data and network latency. Compare complete
finding sets, not only result counts. Record exact source commits and extension
versions. Capture thread concurrency separately from CPU runtime workers.

Raw timings and profiler output are local benchmark artifacts. Only aggregate
findings belong in repository documentation. Re-profile after changing a hot
stage; timings from an earlier implementation do not describe its successor.

## Optimized baseline observations

On extension 0.2.23, with ASCII normalization and similarity already accelerated,
the following diagnostic shares were observed during complete native scans of
6,005 entries at concurrency 40 on a controlled target. Percentages are shares
of exclusive CPU within the measured stages, not total process CPU or RPS:

| Corpus | Largest measured stages |
| --- | --- |
| Static 896 B | Response objects 33.8%, normalization 24.1%, dispatch 12.0%, fingerprints 11.9% |
| Reflected HTML ~4 KiB | Normalization 44.9%, response objects 24.6%, fingerprints 10.2%, dispatch 7.6% |
| Compact JSON ~4 KiB | Similarity 60.5%, normalization 12.6%, response objects 7.8% |

These scans include wildcard preparation and retain the same five control
findings. The static shortcut can already omit later exact misses; dynamic
negatives still construct Python responses before classification. This motivates
compiling calibrated wildcard profiles and moving stateless response comparison
to native workers. Stateful calibration observations must remain ordered, including
responses that need Python fallback. Runtime validation used Linux x86_64,
Python 3.14.5 and Rust 1.88.0.
