# Discovery configuration ownership

`DiscoveryConfig` snapshots the controller's discovery policy and the fuzzer's
calibration variants for one run. `Controller.run()` constructs it after raw
request parsing or session restoration, alongside `RequestConfig` and
`FilterConfig`. It passes the same immutable policy to every target's fuzzer.

| Previous global option reads | Current owner | Consumers |
| --- | --- | --- |
| `crawl`, `find_backup` | `DiscoveryConfig` | Controller root crawl and match callback |
| Recursion flags, status codes, depth and excluded subdirectories | `DiscoveryConfig` | Controller recursion and crawl-path exclusion |
| Initial `subdirs` | `DiscoveryConfig` | Target seeding and progress job count |
| `prefixes`, `suffixes`, `extensions` for wildcard profiles | `DiscoveryConfig` | Threaded, async and native fuzzer calibration |

All migrated internal callers pass policy explicitly. No constructor fallback
reads the global options dictionary. `Crawler` itself remains a stateless parser;
it does not need this config, and its extraction rules are unchanged.

## Policy is not queued work

The policy contains only immutable values. Lists become tuples and recursion
status codes become a frozenset. Their contents are copied from normalized input,
so later option mutations cannot change an existing consumer's decisions.
Ordering, duplicates, empty root entries and existing path semantics are preserved;
this adapter does not replace CLI validation or normalize paths again.

```python
from lib.core.discovery_config import DiscoveryConfig

policy = DiscoveryConfig(
    crawl=True,
    recursive=True,
    recursion_status_codes={200, 301},
    recursion_depth=1,
    subdirs=("",),
    exclude_subdirs=("private/",),
    extensions=("html",),
)
```

Pass it as `discovery_config=policy` when constructing a fuzzer, alongside its
filter policy and callbacks. To change policy, create new configuration and
consumers; do not swap it under a running scan.

The directory queue and visited URLs still belong to the controller. Learned
wildcard profiles still belong to each target's `FilterState`. Dictionary claims
and dynamically queued paths remain Dictionary-owned. This PR neither moves that
mutable state into the config nor changes its lifecycle, locking or ordering.

## Behavior and sessions

Root crawling, match-triggered crawling/backups, same-origin redirect recursion,
depth counting, excluded-subdirectory checks and duplicate-directory suppression
retain their existing implementation. Default calibration prefixes and suffixes
are unchanged. Tests also preserve existing profile construction multiplicity:
threaded/native deduplicate repeated prefixes; async currently iterates them.
Unifying that behavior would be a separate change, not part of this refactor.

Sessions still serialize the existing options and queue/dictionary state.
Loading a session rebuilds `DiscoveryConfig` from restored options before the
first target is processed. The policy itself is not persisted, and the checkpoint
schema and engine-independent resume behavior are unchanged.

## Remaining boundaries

This is an incremental ownership change, not full concurrent-controller support.
Wordlist generation and validation still read their settings through the
wordlist backend. That includes the wordlist use of prefixes/suffixes/extensions,
excluded extensions, transformations and backend selection. Their migration must
cover Dictionary construction/restoration and native-owned corpus behavior in a
separate PR. This change does not materialize or copy the native wordlist.

Scheduling/concurrency/pacing, targets, output, replay settings and other runtime
globals also remain separate steps. No new Rust ABI, chunk parameter, callback
protocol, CLI flag or discovery capability is introduced. No throughput claim is
made.

## Validation

The canonical command is `python -m unittest discover -s tests -t .`.

Coverage includes immutable collections and the complete options adapter,
different calibration variants across all three fuzzer classes, recursion
depth/exclusion/deduplication with global options empty, independent match
discovery flags, and setup/session preparation followed by multiple targets.
The existing loopback CLI contracts, redirect-origin tests, dynamic dictionary
tests and session-resume queue tests continue to exercise production consumers.

The installed-package smoke test imports this module explicitly. Native
integration requires a compatible optional extension and skips when absent.
