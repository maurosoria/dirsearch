# Native wildcard calibration

Native extension 0.2.27 accelerates stable-pattern extraction for ASCII samples
when the native request engine is selected. It preserves the token
SequenceMatcher blocks, autojunk policy, matching ties and the bounded
replacement synchronization window introduced in Python 3.14's Differ. Only
equal words are retained, so intraline display annotations are not constructed.
Unicode retains the standard-library Differ. Native pattern extraction is
enabled on the verified Python 3.14 and 3.15 minors. Other Python minors keep
their own Differ while retaining the native HTTP backend on Python 3.14+.
Threaded and async responses always use Python content algorithms; installing
the extension does not change their normalization or comparison behavior.

CI exercises Python 3.14 and 3.15, including the native extension, and compares
patterns against each runtime's own Differ. The native-pattern tests require
the optimized path on those verified minors whenever a matching extension is
available. Version-boundary tests keep unverified minors on the Python path.

The adapter consumes an immutable public comparison profile. Native calibration
counts remain authoritative when a directory requires Python fallback, allowing
later compatible recursive directories to enable the worker classifier without
losing earlier observations. Logging retains worker classification: compact
metadata records carry exclusions, and calibration decisions are logged only
when their input ranges commit. Filtered bodies are not decoded for diagnostics.

Calibration is sequential in every engine. Each profile completes its probes
and adaptive samples before the next profile starts. A prefix or suffix can
establish a session even when the default profile did not receive cookies;
later probes must observe that updated session. Duplicate-profile reuse and
the ordinary probe budget are preserved.

Statuses configured with `--skip-on-status` stop the target before a calibration
probe becomes a profile. Candidate responses with those statuses bypass native
suppression and stop before explicit filters or wildcard comparisons run.

Tests compare extracted patterns and parser decisions against Python's Differ,
including replacement windows and repetitive reflected bodies. Controlled HTTP
tests verify sequential requests, unchanged probe count and cookies first issued
by a later prefix. Calibration errors and cancellation propagate through
the unfiltered request path.

## Version compatibility research

The relevant upstream changes are:

- Python 3.13 uses recursive replacement synchronization. Python 3.14 replaced
  this with a non-recursive search within ten positions of the corresponding
  token. This is the policy implemented by the native extension.
- Between 3.14.0 and 3.14.10, the SequenceMatcher and Differ class bodies are
  unchanged after removing documentation. Python 3.15.0 and 3.15.2 simplify
  quick-ratio bookkeeping and reuse an already calculated ratio; they preserve
  the synchronization window and comparison thresholds.
- CPython development revision `085d3665b10b8b4a86504a7e6c05c933bbde12bc`
  adds an explicit Differ autojunk option. Its default remains true, matching
  dirsearch's current policy. This is a source comparison, not a claim of
  complete runtime support for an unreleased Python version.

A deterministic offline corpus of 992 ASCII input pairs produced identical
native patterns against the 3.14.0, 3.14.10, 3.15.0, 3.15.2 and development
references. Native similarity also matched the Python reference in 15,244
comparisons. Runtime checks used Python 3.14.5, 3.14.10 and 3.15.2 on Linux.
Source comparisons isolate the two classes; only the newer module-level lazy
import syntax is normalized for parsing on Python 3.14.

Python 3.16.0a1 also loaded the same ABI3 wheel built with Python 3.15.2 and
matched its own standard library in 992 pattern comparisons and 14,644
similarity comparisons. That check covers the native module boundary and
algorithms, not the complete scanner suite or every dependency on Python 3.16.
The complete application suites passed 1,182 tests without skips on both
Python 3.14.10 and 3.15.2; the 3.15 run used an extension built from that runtime.

Primary sources: [bounded Differ change](https://github.com/python/cpython/commit/de19694cfbcaa1c85c3a4b7184a24ff21b1c0919),
[Python 3.15 ratio reuse](https://github.com/python/cpython/commit/79f6caf8f1f52788e15c97debd822e99672e5181),
and [development reference](https://github.com/python/cpython/blob/085d3665b10b8b4a86504a7e6c05c933bbde12bc/Lib/difflib.py).

## Alternative libraries

The same 992 token pairs were compared with explicit adapters that retain only
identical tokens, just as dirsearch does. These are algorithm comparisons, not
counts of incorrect scan findings.

| Library and adapter | Different pattern lists | Implication |
| --- | ---: | --- |
| cdifflib 1.2.9 CSequenceMatcher inside the unchanged Differ | 0 / 992 | Preserves the tested policy, but still delegates replacement synchronization to Python Differ and adds a C extension build. |
| RapidFuzz 3.14.6 LCSseq equal opcodes | 681 / 992 | Changes which fragments become stable patterns. |
| diff-match-patch 20241021, token mapping, raw diff with no timeout | 725 / 992 | Myers-based matching chooses different stable fragments. |
| similar 3.2.0 Myers / Patience / Histogram equal opcodes | 714 / 726 / 483 of 992 | Suitable candidates for a new policy, not direct substitutes for the existing one. |

RapidFuzz's normalized Indel ratio differed in 3,456 of 15,244 comparisons;
280 pairs crossed the existing 0.75 threshold. For example, `aaa` versus `abaa`
scores approximately 0.571 with SequenceMatcher and 0.857 with RapidFuzz.
cdifflib matched all 15,244 tested ratios and compiled on Python 3.14.10 and
3.15.2. It does not remove the dependency on Differ's policy.

The current Rust implementation preserves the tested reference results without
adding a dependency. The subsequent [performance and detection benchmark](diff-library-benchmarks.md)
evaluates these candidates with labelled missing pages and valid routes,
including all request engines on Python 3.14 and 3.15. Similar accelerated some
isolated operations, but showed no consistent full-scan improvement beyond the
unchanged-algorithm control. All candidates shared the labelled corpus's
omissions and false positives. The default implementation remains unchanged.

Library sources: [cdifflib](https://github.com/mduggan/cdifflib),
[RapidFuzz's ratio semantics](https://github.com/rapidfuzz/RapidFuzz/blob/main/api_differences.md),
[maintained diff-match-patch](https://github.com/diff-match-patch-python/diff-match-patch),
and [similar algorithms](https://docs.rs/similar/3.2.0/similar/algorithms/index.html).
