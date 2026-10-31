# Diff library performance and detection results

Measured on 2026-10-29 against dirsearch source
`31b008a42b2f48a0db0eb1327b4105248d9b562f`.

## Decision

Keep the current Rust implementation for now. Similar is a viable candidate
for a deliberate change of matching policy, but faster isolated comparisons
do not establish a consistent full-scan improvement. No runtime dependency or
filtering policy was changed by this research.

Similar Myers extracted stable words about 1.8x faster on the reflected HTML
sample, but was about 5.3x slower on the reordered sample. RapidFuzz had the
fastest character-similarity operation on ordinary HTML. Both results need to
be read alongside the complete scans and detection counts below.

## Measurement contracts

- Linux x86_64, four dedicated vCPUs, 8 GiB RAM, Rust 1.88.0. Full timing
  matrices used Python 3.15.2; all operation benchmarks also ran on 3.14.10.
- Fixed source snapshots, separate Cargo targets and installed wheels. Adding
  Similar did not change existing dependency versions. A research control kept
  the original algorithm with the experimental dispatch enabled.
- One warmup and five measured repetitions per timing cell, with deterministic
  shuffled candidate order. Tables report medians; relative speeds are geometric
  means of paired median speed ratios, within each comparison group.
- Native HTTP concurrency 40, four runtime workers, Python wordlist backend,
  no recursion, zero retries, empty configuration and identical wordlists.
  End-to-end time includes process startup, calibration, requests and JSON output.
- Twelve labelled response families: 9,480 distinct paths, including 360 valid
  routes. Samples cover reflected paths, short tokens, compact JSON, reordered
  sections, repeated words, Unicode, variable lengths and valid 404 responses.
  Bodies have nominal sizes from 1 to 64 KiB. Labels come from the controlled
  server's route map, independently of any library's output.
- Two additional timing cases each scan 10,000 distinct routes, including 30
  positives. The server verifies the exact requested path set, count and absence
  of duplicate requests. Calibration probe counts are recorded separately.
- 910 accepted measured full scans, plus their 182 warmups; 384 operation cells;
  360 functional checks across threaded, async and native request engines on
  Python 3.14.10 and 3.15.2. The functional matrix selects the control, all three
  full Similar modes and RapidFuzz. Request accounting passed in every accepted
  full scan and functional check; no accepted operation timed out or failed.

The research control preserved the pristine build's complete finding sets and
probe counts. The Python-adapter timing cells were rerun after fixing their RNG
initialization order; the earlier cells are excluded. Two native case groups
were also repeated without auxiliary diagnostic work. Raw evidence and temporary
runners are retained outside version control.

The separate [version research](native-calibration.md#version-compatibility-research)
describes the Python 3.16 module checks; the timing matrix covers 3.14 and 3.15.

## Complete scan timing

The native group changes the functions used inside the Rust worker as well as
the Python exports. “Patterns” changes stable-word extraction only; “patterns +
ratio” also changes character similarity. Unicode stable-word extraction keeps
the existing Python Differ fallback in this group.

| Variant | HTML 10,000 paths, RPS | JSON 10,000 paths, RPS | Relative speed, 12 cases | Relative speed, 10,000 paths |
| --- | ---: | ---: | ---: | ---: |
| Current implementation | 7,374 | 7,982 | 1.000x | 1.000x |
| Research control | 7,527 | 8,467 | 0.989x | 1.041x |
| Similar Myers, patterns | 7,878 | 8,095 | 0.995x | 1.041x |
| Similar Patience, patterns | 7,552 | 8,261 | 0.995x | 1.030x |
| Similar Histogram, patterns | 7,468 | 8,113 | 1.003x | 1.015x |
| Similar Myers, patterns + ratio | 7,618 | 7,890 | 0.992x | 1.011x |
| Similar Patience, patterns + ratio | 7,529 | 8,418 | 0.997x | 1.038x |
| Similar Histogram, patterns + ratio | 7,654 | 8,184 | 0.990x | 1.032x |

Across the two 10,000-path cases, Myers patterns measured 1.041x the pristine
build and the unchanged-algorithm research control measured 1.041x as well.
Myers therefore measured approximately 1.000x the control. The apparent four
percent improvement is also present without changing the algorithm and cannot
be attributed to Similar. The smaller-case matrix also shows no consistent gain.

The Python group sends every candidate through the same Python classification
path, with the Rust wildcard shortcut disabled. Its reference still calls the
current Rust content functions. This prevents the worker shortcut from bypassing
the library being measured. Compare relative speeds within this group.

| Variant | HTML 10,000 paths, RPS | JSON 10,000 paths, RPS | Relative speed, 12 cases | Relative speed, 10,000 paths |
| --- | ---: | ---: | ---: | ---: |
| Current Rust functions | 3,998 | 5,369 | 1.000x | 1.000x |
| Python difflib | 3,977 | 5,321 | 0.960x | 0.993x |
| cdifflib | 3,919 | 5,262 | 0.965x | 0.980x |
| RapidFuzz | 3,712 | 5,582 | 1.001x | 0.983x |
| diff-match-patch | 3,923 | 3,053 | 0.786x | 0.747x |

Median peak RSS across the 10,000-path cases was about 71 MiB for the native
group and 120-121 MiB for the Python-adapter group. All Python
adapters import the same library set, so their RSS includes that shared research
harness and should not be interpreted as an individual dependency's memory cost.

## Detection quality

All 13 candidates produced the same exact finding sets in every accepted timing cell.
Across the twelve labelled families the current implementation found 340 of 360
valid routes, omitted 20 and reported 1,298 nonexistent routes. These are stress
corpus results, not an estimate of accuracy on arbitrary sites.

| Response family | Valid routes found | False positives | Valid routes missed |
| --- | ---: | ---: | ---: |
| Short-token HTML | 20 | 0 | 10 |
| Valid pages retaining the error-page envelope | 20 | 0 | 10 |
| Reordered error-page sections | 30 | 649 | 0 |
| Error pages with variable-length sections | 30 | 649 | 0 |
| Other eight families combined | 240 | 0 | 0 |

The explicit valid-404 family retained all 30 positives. No blanket 404 exclusion
was applied. Every large timing cell retained its 30 positives without false
positives. The selected candidates also preserved exact finding sets across
both Python versions and all three request engines in the 360 functional checks.

The shared omissions and false positives did not disappear when replacing the
diff algorithm. Further calibration work should evaluate multiple error-page
layouts and valid pages sharing their surrounding template. These results do
not justify treating similarity alone as evidence that a route is nonexistent.

## Isolated operation timing

Representative Python 3.15.2 medians in microseconds per call; smaller is faster.
Normalization is performed before timing. Pattern timings include tokenization
and materializing the returned stable words. These are function timings, not
request throughput.

| Adapter | HTML patterns | Reordered patterns | HTML similarity | Reordered similarity |
| --- | ---: | ---: | ---: | ---: |
| Current Rust | 99.5 | 94.9 | 26.6 | 55.7 |
| Python difflib | 529.4 | 418.2 | 1,493.3 | 2,677.2 |
| cdifflib | 370.6 | 460.1 | 1,421.8 | 1,583.6 |
| RapidFuzz | 66.6 | 128.3 | 2.6 | 229.4 |
| diff-match-patch | 203.5 | 8,194.9 | 99.6 | 13,264.0 |
| Similar Myers | 54.9 | 500.8 | 11.5 | 577.8 |
| Similar Patience | 87.4 | 180.4 | 170.6 | 673.4 |
| Similar Histogram | 69.6 | 180.3 | 18.5 | 1,303.0 |

For 64 KiB reflected HTML, current Rust / Similar Myers / RapidFuzz took
approximately 2,279 / 1,346 / 1,271 microseconds for patterns and
461 / 80 / 35 microseconds for similarity. Similar's advantages depend on input
structure; the reordered case reverses several comparisons. The same qualitative
tradeoffs occurred on Python 3.14.10.

## Adapter semantics and recommendation

Pinned candidates were Similar 3.2.0, RapidFuzz 3.14.6, cdifflib 1.2.9 and
Python diff-match-patch 20241021.

- Similar uses `capture_diff_slices` over words for patterns and characters for
  similarity. The experimental ratio is `2 * equal_characters / total_characters`
  from that algorithm's equal operations, without SequenceMatcher autojunk.
  Myers, Patience and Histogram are separate policies; default Myers includes
  heuristics and is not a promise of the same matches as Differ.
- RapidFuzz uses LCSseq equal token opcodes and normalized Indel character
  similarity. It changes the meaning of the existing thresholds.
- cdifflib replaces SequenceMatcher inside otherwise unchanged Python Differ;
  it retains Differ's Python-version policy and replacement synchronization.
- diff-match-patch maps words to tokens, disables its timeout and line heuristic,
  and retains raw equal operations without semantic cleanup. The full scan
  controller still bounds execution time.

The existing deterministic 992-pair comparison demonstrates that these
alternatives can select different fragments even when this labelled corpus
produces identical final decisions. The corpus is not proof of equivalence on
unseen sites. Similar remains worth considering to reduce custom matching code,
with an explicit policy review; the measured performance alone does not justify
switching the default. Changing the library also does not solve the shared
calibration limitations demonstrated here.

Primary references: [Similar algorithms and heuristics](https://docs.rs/similar/3.2.0/similar/algorithms/index.html),
[Similar sequence API](https://docs.rs/similar/3.2.0/similar/fn.capture_diff_slices.html),
[RapidFuzz ratio](https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html#ratio),
[cdifflib](https://github.com/mduggan/cdifflib), and
[maintained diff-match-patch](https://github.com/diff-match-patch-python/diff-match-patch).
