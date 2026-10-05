# Local state ownership backlog

This is the state-isolation backlog following PR #1741, including the
result-policy refactor in this branch. It is not a list of all product issues, nor
a claim that multiple complete controllers can already share a process safely.
Keep subsequent steps independently reviewable, with explicit contracts and
regressions before replacing their callers.

## Completed boundaries

- Immutable `WordlistConfig`, `RequestConfig`, `FilterConfig`, `DiscoveryConfig`,
  `ExecutionConfig`, `ReportConfig`, `TargetConfig`, `TerminalConfig`,
  `LogConfig` and `ResultConfig` snapshots.
- Instance-owned mutable `FilterState` and explicit `ScanEngine` selection.
- `ScanRunState` separates pending targets from the active target, preserving
  the existing engine-independent checkpoint representation.
- Python display-rate caching is now requester-owned. The 150 ms interval,
  request pacing and Rust rate accounting are unchanged.
- [Terminal configuration](terminal-configuration.md), output history and stream
  adaptation are controller-owned; color tables are read-only. No terminal is
  created at module import and cleanup no longer depends on a global `atexit` hook.
- [Logging](logging-ownership.md) is controller-owned, with a detached redaction
  policy, no named global logger, and handler cleanup after its borrowers.
- [Result policy](result-configuration.md) fixes response destinations, full-URL
  presentation and replay selection per run; transport composition derives its
  capture flag from that prepared policy. Store lifecycle and native body limits
  are unchanged.

## Remaining work, in suggested order

| Order | Boundary | Completion criterion |
| --- | --- | --- |
| 1 | Session preparation and persistence | Export prepared configuration plus owned progress, not the process-wide options map; preserve cross-engine resume and the current schema contract. |
| 2 | Aggregate configuration and local context | Group prepared policies without a giant parameter list; separate configuration, live resources and mutable progress. Assign ownership to run metadata and generator state without changing generation behavior. |
| 3 | CLI options boundary | Keep mutable normalization local to one invocation; remove the global `options` dictionary once its last consumers are migrated. |
| 4 | Constant tables | Make read-only intent enforceable where compatible, including `TEXT_CHARS`, and review the duplicate default-port mappings. |
| 5 | Isolation acceptance tests | Prove independent local lifecycles, output, failure cleanup and resume without process-global patching; address signal ownership and ambient raw-target context. Passing component tests alone is insufficient. |

Steps 1-3 build on the explicit component boundaries; add isolation tests along
the way, with step 5 as the final acceptance gate. Any future public task/context
API must distinguish serializable task data from live handles and Rust's existing
internal `ScanTask`; no parallel-target, GUI or remote scheduling is added here.

## Module-level mutable dictionaries

Inventory scope: first-party Python runtime files in `lib/` and `dirsearch.py`;
module-level dictionary literals, comprehensions and dictionary constructors.
Tests, third-party internals, per-instance fields and dynamically created aliases
are not counted. Writes were checked separately from the declared types.

One remaining module-level dictionary is modified by production code:

| Name | Location | Remaining responsibility |
| --- | --- | --- |
| `options` | `lib/core/data.py` | CLI normalization, controller composition and session integration. |

`BACK_COLORS`, `FORE_COLORS` and `STYLES` are now read-only mapping proxies;
`disable_color()` was removed. `lib/core/decorators.py::_cache` was removed with
the unused `cached` decorator in PR #1739. The `locked` decorator remains
and continues to use its instance's operation lock.

Seven other dictionaries are mutable by type but have no identified production
writes; these are constant tables or a static registry, not equivalent to shared
runtime progress:

| Name | Location |
| --- | --- |
| `SIZE_UNITS` | `lib/core/filters.py` |
| `WORDLIST_CATEGORIES` | `lib/core/settings.py` |
| `STANDARD_PORTS` | `lib/core/settings.py` |
| `DEFAULT_HEADERS` | `lib/core/settings.py` |
| `DEFAULT_PLACEHOLDERS` | `lib/core/wordlist_template.py` |
| `_DEFAULT_PORTS` | `lib/parse/url.py` |
| `output_handlers` | `lib/report/manager.py` |

The remaining direct importers of global `options` are `dirsearch.py` and
`lib/controller/controller.py`. Logging no longer reads it, including through
`options.get(...)`, or owns a process-global handler.

## Other global state and import-time values

This inventory distinguishes mutable state from read-only data; it does not list
every scalar constant, compiled regex, imported module or third-party singleton.

| Name / mechanism | Location | Ownership concern |
| --- | --- | --- |
| `_stealth_word_generator` | `lib/utils/random.py` | Holds a mutable RNG and growing `_seen` set for the entire process; choose explicit ownership without changing generation behavior. |
| `_request_target_state` | `lib/connection/requester.py` | `threading.local()` raw-target context: separate per thread, but still ambient. |
| Signal registrations | `Controller.run()` | Process-wide handlers; installation/restoration needs an explicit owner. |
| `COMMAND`, `START_TIME` | `lib/core/settings.py` | Immutable strings captured at import rather than per invocation. |
| `TEXT_CHARS` | `lib/core/settings.py` | Mutable `bytearray` used as a read-only binary-detection table; no production writes identified. |
| `__all__` lists | `lib/core/api.py`, `dirsearch.py` | Static export metadata, not run progress. |

Import-time platform/path constants also remain, but are not mutable progress.
The generator uses its own `random.Random`; other utility calls additionally
borrow the standard library's default RNG. None of these are changed by the
logging refactor. Inspected native maps and wordlist indexes are
session/instance-owned, not additional process-global mutable dictionaries;
native task-local contexts likewise are not shared global progress maps.
