# Phase 5 Native Request Backend Benchmarks

These artifacts capture the DigitalOcean benchmark runs used to evaluate the
experimental Rust request backend for `dirsearch`.

## Result Files

- `results/do-vulnweb-native-impl.json`: remote benchmark against public Vulnweb targets.
- `results/do-local-contention.json`: single-droplet nginx loopback benchmark with direct HTTP clients and parallel `dirsearch` processes.
- `results/do-split-matrix.json`: two-droplet benchmark with nginx on a dedicated target droplet and scanner droplets at 2, 4, and 8 vCPU.
- `results/do-split-s-*.json`: raw per-scanner outputs used by the split matrix.

## Reproduction

Use a fresh DigitalOcean token through the environment. Do not write it into
scripts, result files, shell history, or docs.

```sh
DIGITALOCEAN_ACCESS_TOKEN=... \
TARGET_SIZE=s-4vcpu-8gb \
SCANNER_SIZES=s-2vcpu-4gb,s-4vcpu-8gb,s-8vcpu-16gb \
RESULT_FILE=phase5-do-split-matrix-result.json \
RESULT_DIR=phase5-do-split-results \
LOCAL_PROCESS_COUNTS=8 \
LOCAL_THREADS_PER_PROCESS=12 \
LOCAL_REPEATS=3 \
TIMEOUT=5 \
scripts/run_phase5_do_split_matrix.sh
```

The split benchmark creates one nginx target droplet and one scanner droplet per
size. Cleanup is handled by traps, but always verify afterwards:

```sh
doctl compute droplet list --tag-name dirsearch-phase5-benchmark
doctl compute ssh-key list | rg 'dirsearch-(split|phase5)'
rg -n 'dop[_]v1_' . --glob '!/.git/**' --glob '!/.venv/**' --glob '!build/**'
```

## Split Target Matrix

Target: nginx on `s-4vcpu-8gb`. Scanner: 8 `dirsearch` processes, 12 threads per
process, 3 repeats, 1000 paths per process.

| Scanner | Rust median | Python median | Rust vs Python | Rust best | Python best |
|---|---:|---:|---:|---:|---:|
| `s-2vcpu-4gb` | 1231.7 RPS | 528.6 RPS | 2.33x | 1245.4 RPS | 558.0 RPS |
| `s-4vcpu-8gb` | 2115.1 RPS | 853.9 RPS | 2.48x | 2221.9 RPS | 913.6 RPS |
| `s-8vcpu-16gb` | 4002.1 RPS | 1418.7 RPS | 2.82x | 4040.4 RPS | 1538.3 RPS |

The native path scaled with scanner CPU because the fixed 8-process workload had
less scheduler contention as vCPUs increased. Context switches also fell
sharply for native: at 8 vCPU the median was 7059 for native vs 227172 for
Python.

## Direct HTTP Client Matrix

Best median direct Rust result per scanner size:

| Scanner | Best concurrency | Rust median | Requests median | Rust vs requests |
|---|---:|---:|---:|---:|
| `s-2vcpu-4gb` | 12 | 3046.7 RPS | 485.4 RPS | 6.28x |
| `s-4vcpu-8gb` | 50 | 4238.3 RPS | 360.3 RPS | 11.76x |
| `s-8vcpu-16gb` | 50 | 8395.3 RPS | 489.6 RPS | 17.15x |

## Loopback Contention Baseline

Single droplet, nginx loopback, 12 threads per `dirsearch` process:

| Processes | Native median | Python median | Native vs Python |
|---:|---:|---:|---:|
| 1 | 530.7 RPS | 324.2 RPS | 1.64x |
| 2 | 1011.9 RPS | 439.4 RPS | 2.30x |
| 4 | 1094.3 RPS | 472.0 RPS | 2.32x |
| 8 | 1098.9 RPS | 489.4 RPS | 2.25x |

## Notes

- Runtime workers and HTTP in-flight concurrency are separate. Rust CPU workers
  should track available CPUs, while HTTP concurrency should remain higher than
  CPU count for I/O-bound scans.
- A practical default for native HTTP concurrency is
  `min(max(cpu_count * 8, 12), 128)`, with explicit CLI overrides preserved.
- Always report medians first. Include best values only as secondary context.
