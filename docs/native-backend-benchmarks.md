# Native Backend Benchmark Results

These results summarize the Phase 5 benchmark runs used to evaluate the
experimental Rust native request backend. Raw benchmark outputs and runner
scripts are intentionally not stored in the repository.

The benchmark numbers below report medians first. Best samples are included only
as secondary context because they are more sensitive to transient host and
network conditions.

## Split Target Matrix

Target: nginx on a dedicated `s-4vcpu-8gb` DigitalOcean droplet.

Scanner setup: one scanner droplet per size, 8 `dirsearch` processes, 12
threads per process, 3 repeats, and 1000 paths per process.

| Scanner | Rust median | Python median | Rust vs Python | Rust best | Python best |
|---|---:|---:|---:|---:|---:|
| `s-2vcpu-4gb` | 1231.7 RPS | 528.6 RPS | 2.33x | 1245.4 RPS | 558.0 RPS |
| `s-4vcpu-8gb` | 2115.1 RPS | 853.9 RPS | 2.48x | 2221.9 RPS | 913.6 RPS |
| `s-8vcpu-16gb` | 4002.1 RPS | 1418.7 RPS | 2.82x | 4040.4 RPS | 1538.3 RPS |

The native path scaled with scanner CPU because the fixed 8-process workload had
less scheduler contention as vCPU count increased. Context switches also fell
sharply for native: at 8 vCPU the median was 7059 for native vs 227172 for
Python.

## Direct HTTP Client Matrix

Best median direct Rust result per scanner size:

| Scanner | Best concurrency | Rust median | Requests median | Rust vs requests |
|---|---:|---:|---:|---:|
| `s-2vcpu-4gb` | 12 | 3046.7 RPS | 485.4 RPS | 6.28x |
| `s-4vcpu-8gb` | 50 | 4238.3 RPS | 360.3 RPS | 11.76x |
| `s-8vcpu-16gb` | 50 | 8395.3 RPS | 489.6 RPS | 17.15x |

These direct HTTP numbers isolate client overhead. They are useful for comparing
transport cost, but they are not equivalent to full `dirsearch` scan throughput.

## Loopback Contention Baseline

Single droplet, nginx loopback, 12 threads per `dirsearch` process:

| Processes | Native median | Python median | Native vs Python |
|---:|---:|---:|---:|
| 1 | 530.7 RPS | 324.2 RPS | 1.64x |
| 2 | 1011.9 RPS | 439.4 RPS | 2.30x |
| 4 | 1094.3 RPS | 472.0 RPS | 2.32x |
| 8 | 1098.9 RPS | 489.4 RPS | 2.25x |

The contention benchmark includes fuzzer, callbacks, filters, process overhead,
and scheduler behavior. It is the better reference for expected full-scan gains.

## Operating Notes

- Runtime workers and HTTP in-flight concurrency are separate knobs.
- Rust CPU workers should track available CPUs.
- HTTP concurrency should usually remain higher than CPU count for I/O-bound
  scans.
- A practical native HTTP concurrency default is
  `min(max(cpu_count * 8, 12), 128)`, while preserving explicit CLI overrides.

## Incremental Result Delivery Regression Check

Native extension 0.2.18 was measured on a dedicated 4-vCPU Linux host with the
whole-result collection and incremental ordered chunks in the same
release build. A local nginx target ran outside the Python 3.14 benchmark
process. Each sample scanned 30000 paths at concurrency 128, using the
corresponding 12800-path `NativeFuzzer` chunk size. One engine and connection
pool remained alive across 15 balanced-order samples so the comparison isolates
result delivery rather than pool startup. This is a direct engine comparison,
not a full `dirsearch` contention result.

| Results | Whole-result median | Incremental median | Incremental / whole-result | Median callbacks | Median first delivery |
|---|---:|---:|---:|---:|---:|
| All filtered | 38023.9 RPS | 37956.1 RPS | 1.00x | 40 | 25.2 ms |
| 5% actionable | 37490.6 RPS | 37671.8 RPS | 1.00x | 50 | 26.8 ms |

A tuning sweep covered caps from 1024 to 4096 paths and flush targets from 10
to 40 ms. A per-completion Tokio channel initially limited every incremental
configuration to 0.91-0.92x whole-result throughput. Replacing it with the shared
completion bitmap restored 0.998-1.005x median throughput. The 2048-path cap plus
20 ms flush target was retained as the balanced point: 25 ms saved 7 callbacks
per 30000 filtered paths and 7 per 30000 mixed paths, but added about 4-5 ms to
first delivery without a measurable throughput gain. Treat sub-percent deltas
as benchmark noise rather than production speedups. Raw benchmark output and
the temporary runner were not committed.
