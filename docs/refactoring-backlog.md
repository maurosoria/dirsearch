# Local state ownership backlog

This is the state-isolation backlog following PR #1739, including the
terminal-ownership refactor. It is not a list of all product issues, nor
a claim that multiple complete controllers can already share a process safely.
Keep subsequent steps independently reviewable, with explicit contracts and
regressions before replacing their callers.

## Completed boundaries

- Immutable `WordlistConfig`, `RequestConfig`, `FilterConfig`, `DiscoveryConfig`,
  `ExecutionConfig`, `ReportConfig`, `TargetConfig` and `TerminalConfig` snapshots.
- Instance-owned mutable `FilterState` and explicit `ScanEngine` selection.
- `ScanRunState` separates pending targets from the active target, preserving
  the existing engine-independent checkpoint representation.
- Python display-rate caching is now requester-owned. The 150 ms interval,
  request pacing and Rust rate accounting are unchanged.
- [Terminal configuration](terminal-configuration.md), output history and stream
  adaptation are controller-owned; color tables are read-only. No terminal is
  created at module import and cleanup no longer depends on a global `atexit` hook.

## Remaining work, in suggested order

| Order | Boundary | Completion criterion |
| --- | --- | --- |
| 1 | Logging and redaction | Explicit logging/redaction policy and handler lifetime; no ambient `options` reads or handler replacement affecting another run. |
| 2 | Response capture and result presentation | Snapshot response destinations, full-URL presentation and replay policy; preserve capture completeness, write draining and existing replay behavior. |
| 3 | Session preparation and persistence | Export prepared configuration plus owned progress, not the process-wide options map; preserve cross-engine resume and the current schema contract. |
| 4 | Aggregate configuration and local context | Group prepared policies without a giant parameter list; separate configuration, live resources and mutable progress, with explicit cleanup ownership. |
| 5 | CLI options boundary | Keep mutable normalization local to one invocation; remove the global `options` dictionary once its last consumers are migrated. |
| 6 | Constant tables | Make read-only intent enforceable where compatible, and review the duplicate default-port mappings. |
| 7 | Isolation acceptance tests | Prove independent local lifecycles, output, failure cleanup and resume without process-global patching; address process signal ownership. Passing component tests alone is insufficient. |

Steps 1-3 have separate ownership concerns and can be scoped independently.
Steps 4-5 depend on making those boundaries explicit; add isolation tests along
the way, with step 7 as the final acceptance gate. Any future public task/context
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

The remaining direct importers of global `options` are `dirsearch.py`,
`lib/controller/controller.py` and `lib/core/logger.py`.
In particular, logging still reads `options.get("proxy_auth")` during redaction;
searching only for `options[...]` misses this dependency.

Other shared state is not a dictionary: logging `logger`/handlers, process signal
handlers, requester thread-local raw-target context and import-time
`COMMAND`/`START_TIME` run metadata also need explicit ownership decisions.
Thread-local context is not shared between threads, but is still ambient rather
than explicitly passed. The run metadata strings are immutable but process-wide.
Inspected native maps and wordlist indexes are session/instance-owned, not
additional process-global mutable dictionaries.
