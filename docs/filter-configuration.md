# Filter configuration and calibration ownership

`FilterConfig` holds one run's immutable matching policy. `Controller.run()`
builds it after raw-request parsing or session restoration, alongside
`RequestConfig`. The controller supplies the same policy to every target's
fuzzer and, for native execution, to `NativeRequester`.

| Previous storage or adapter | Current owner | Lifetime |
| --- | --- | --- |
| Filter keys read directly from global `options` | Frozen `FilterConfig` | One run |
| Global `blacklists` holding Dictionary objects | Read-only mapping of path tuples in `FilterConfig` | One run |
| Fingerprint counters, calibration set and lock on the fuzzer | `FilterState` | One target |
| Wildcard profile groups on the fuzzer | `FilterState.scanners` | One target, updated during directory calibration |
| `native_filter_options()` mapping adapter | `FilterConfig.native_options()` | Called at lazy native filter creation |

These are internal contracts; callers now pass configuration explicitly. There
is no compatibility fallback that reads global options when a config is omitted.

## Immutable policy, mutable observations

Status/size sets become frozensets, sequences become tuples, and nested numeric
ranges and time comparisons become immutable pairs. Blacklists are copied to a
read-only mapping with tuple values. Mutating the original CLI/session mapping,
its collections, or a Dictionary after construction cannot change this policy.
Normal CLI/session validation still owns validation; this is not another parser.

Every fuzzer creates a fresh `FilterState`, including when two fuzzers share the
same `FilterConfig`. Counts still span directories within that target. They are
not reset by pause/resume of the running fuzzer, and cannot bleed into the next
target. Counter check/increment operations remain under the same per-target
lock; no I/O, callbacks or awaits run inside those critical sections.

Scanners receive `filter_config` and a calibration `delay` explicitly. Their
default `tested` mapping is now created per instance. Callers can deliberately
pass a target's profile group to reuse an existing wildcard profile, but no
default mapping shares profiles across unrelated scanners.

```python
from lib.core.filter_config import FilterConfig

policy = FilterConfig(
    include_status_codes={200, 403},
    exclude_texts=("maintenance page",),
    filter_threshold=3,
    blacklists={403: ("/blocked",)},
)
```

Pass this policy as `filter_config=policy` to the fuzzer and native requester.
Fuzzers also require an explicit `discovery_config`, described in
[discovery configuration](discovery-configuration.md), and `execution_config`,
described in [execution configuration](execution-configuration.md).
Create a new policy and new consumers when changing run settings; do not swap
the policy on a running consumer, whose observations or native filters may
already reflect the old one.

## Native execution

The Python config translates the same subset of filters that Rust already
supports. The Rust filter object is still created lazily and cached. Replay and
calibration still use an empty native filter configuration, so matching policy
does not prevent those requests from returning their responses.

Python continues to apply the remaining policy and target-local calibration.
The Rust ABI, request loop, chunk sizes and callback protocol are unchanged.
There is no new Python/Rust call per response; this refactor does not claim a
measured throughput improvement.

## Distinct-content safeguards

Repeated-response calibration fingerprints include the exact length and hash
of the complete normalized text, along with status, media type and redirect.
Two pages that share a layout beyond the first 4 KiB no longer become the same
fingerprint merely because their distinguishing content appears later. Existing
dynamic-token and reflected-path normalization, repetition thresholds and
explicit `--filter-threshold` behavior remain in effect. This does not turn a
repeated response into independent evidence that a resource is missing.

When dynamic samples have no common whitespace-delimited tokens, the parser
matches only an already observed normalized sample. It no longer treats the
empty pattern list as a match for every candidate. The scanner's existing
similarity fallback remains separate, and static/known-negative responses still
match. This applies to threaded, async and native execution's shared Python
calibration pipeline.

`--log scan.log` now records normal wildcard-profile and duplicate-threshold
discards, including status and reported/captured body lengths. Wildcard messages
also identify the profile context and sample count. Existing auto-calibration
messages remain available. Logs do not contain response bodies or a complete
native transport trace, and enabling logging is not a byte-for-byte capture.

## Sessions and remaining globals

Sessions still persist normalized option data, not these runtime objects. Resume
rebuilds both configs and now loads the bundled blacklists through the same
preparation path as a new run. Previously blacklist loading lived only in
`setup()`, which session restoration bypasses. No checkpoint schema migration
or engine-specific serialization is introduced, and learned calibration state
is still rebuilt when loading a saved session.

This step removes global filter-policy reads and the global blacklist store.
Controller discovery flags and calibration prefixes/suffixes/extensions now use
`DiscoveryConfig`; blacklist and dictionary generation/validation use
[WordlistConfig](wordlist-configuration.md). This does **not** finish global-state
removal: [ExecutionConfig](execution-configuration.md) now owns engine selection,
fuzzer concurrency/pacing and stop policy. [ReportConfig](report-configuration.md)
owns report destinations and SQLite batch policy. Remaining controller state
and logging still have separate ownership work ahead. Full concurrent
controllers are not yet supported.

## Validation

The normal `python -m unittest discover -s tests -t .` suite includes:

- Deep immutability and adapters independent of the global options dictionary.
- Filter/calibration-state isolation for threaded, async and native fuzzers.
- Fresh target state and shared immutable policy after setup or session restore.
- Explicit sync/async scanner calibration policy without ambient options.
- Existing atomic threshold, native lazy/replay/reopen and loopback CLI contracts.
- Installed-package imports for both new modules.

Native integration tests require the matching optional extension and skip when
it is absent. The CLI contract uses a deterministic loopback server, not an
external target.
