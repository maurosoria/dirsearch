# Native response processing profile

Use `scripts/profile_native_processing.py --output stages.json --` followed by
ordinary dirsearch arguments selecting the native request backend. It measures
Python thread CPU in normalization, similarity, pattern comparison, calibration,
response construction, filters and dispatch. Exclusive time subtracts nested
stages; inclusive percentages must not be added together.

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
