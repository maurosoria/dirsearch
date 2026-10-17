# Local state ownership backlog

This is the state-isolation backlog following PR #1753, including
invocation-local options in this branch. It is not a list of all product issues, nor
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
- [Run/target progress](scan-run-state.md) now separates cumulative counters and
  scheduled-directory history (`ScanRunState`) from the current origin, starting
  path and directory queue (`TargetProgress`). Preparation preserves restored
  totals. Existing sequential lifetimes and the flat session schema are unchanged;
  this is not yet an independently executable task model.
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
- [Session snapshots](session-snapshots.md) detach persistence input from live
  controllers. Export uses prepared options plus owned progress; storage no
  longer creates runtime resources. Version-1 JSON and cross-engine resume stay
  unchanged. Persistence input now has an explicit owner described below.
- Typed `RunCheckpoint`, `TaskCheckpoint` and `DictionaryCheckpoint` values now
  separate cumulative run data from current-target continuation. Both save and
  load use `SessionSnapshot`; storage owns wire names and legacy defaults.
  Progress values are immutable, restoration creates fresh mutable containers,
  and the JSON schema is unchanged. `TaskCheckpoint` is not a runnable descriptor
  or an independently portable session.
- Immutable `TaskSpec` entries now retain original target input separately from
  prepared origin/progress. `ScanRunState` owns descriptor ordering;
  `SessionSnapshot.remaining_tasks` associates its head with `task_checkpoint`.
  Only storage maps the queue to version-1 `options.urls`. Duplicates retain
  their positions; no globally unique IDs or independently runnable tasks exist.
- [Invocation metadata](run-metadata.md) now captures the redacted command and
  date per invocation and shares one immutable `RunMetadata` with reports and
  session path formatting. `COMMAND` and `START_TIME` import-time captures are
  removed. Numeric checkpoint/deadline start times and report schemas are unchanged.
- [Run configuration](run-configuration.md) now groups all ten policies, prepared
  from one detached normalized input after raw parsing or validated resume.
  Consumers still receive narrow policies. Blacklist attachment preserves other
  policy identities; metadata, input, resources and progress remain separate.
  Complete controller isolation is not claimed.
- [SessionOptions](session-options.md) now encapsulates persistence input with
  copy-in/copy-out access, preserving normalized types, unknown fields and absent
  values. Snapshots share the opaque value, not an editable options dictionary;
  save-destination changes replace it. JSON encoding stays in storage. Runtime
  policies are not reverse-serialized. CLI normalization is now invocation-local.
- [RunResources](run-resources.md) now owns live terminal, logger, report manager,
  requester, event loop and response stores. The controller still constructs
  them; teardown preserves report/requester/store/terminal/logger ordering and
  attempts downstream phases after failure. Early report finishing and final
  cleanup do not retry failed releases. Configuration, progress, worker draining
  and persistence stay separate.
- [Controller lifecycle](controller-lifecycle.md) now separates construction from
  execution. `Controller(options)` captures input/metadata/stream and initializes
  local state without opening handles. Explicit, single-use `run()`
  owns bootstrap, fresh/resume preparation, the unchanged target loop and final
  cleanup. Failures cannot silently reuse the same owner. Process signals still
  prevent claiming complete controller isolation.
- [Calibration words](calibration-word-ownership.md) now belong to each fuzzer,
  shared by all its profiles and recursive directories across the three engines.
  Standalone scanners own a generator unless one is injected. The global RNG
  and seen-word history are removed; generation rules and native chunk scanning
  are unchanged. History is no longer retained across unrelated targets.
- [Invocation-local options](invocation-options.md) replace the final actively
  mutated module-level options dictionary. Each CLI entry gets fresh defaults;
  controllers deep-copy input before raw parsing or session restoration. Tests
  own their fixtures, and the old data module is removed without a global shim.
  Session wire formats, normalization precedence and the public API are unchanged.

## Remaining work, in suggested order

| Order | Boundary | Completion criterion |
| --- | --- | --- |
| 1 | Constant tables | Make read-only intent enforceable where compatible, including `TEXT_CHARS`, and review the duplicate default-port mappings. |
| 2 | Isolation acceptance tests | Prove independent local lifecycles, output, failure cleanup and resume without process-global patching; address signal ownership and ambient raw-target context. Passing component tests alone is insufficient. |

Constant-table cleanup can proceed independently; add isolation tests along
the way, with step 2 as the final acceptance gate. Any future public task/context
API must distinguish serializable task data from live handles and Rust's existing
internal `ScanTask`; no parallel-target, GUI or remote scheduling is added here.

## Broader architectural roadmap

Removing globals is a prerequisite, not completion of the architecture work.
The stages below retain completed foundations; their remaining capabilities are
proposals, not implemented features or release promises:

1. Complete the task/progress/checkpoint and aggregate-configuration boundaries
   above. The current `TaskCheckpoint` is only one part of a run-level
   `SessionSnapshot`. Input descriptors exist, but independent execution
   identity, per-task policy and resource ownership are still missing.
2. Complete local lifecycle isolation. Construction, preparation, execution and
   closure are now separate phases with owned live resources; process signals
   and event-loop policy still need an explicit owner at the CLI boundary.
3. Prove independent lifecycle, cancellation, persistence and output isolation
   before allowing complete concurrent executions.
4. Define backend-independent result/lifecycle events for CLI and future UI
   consumers, retaining chunk-oriented native boundaries.
5. Design local task concurrency separately from request concurrency within a
   target, with deterministic lifecycle and checkpoint acceptance tests.
6. Only afterward consider GUI/external orchestration adapters using data
   contracts rather than serialized live runtime objects. Remote scheduling is
   a separate future design, not part of these state-isolation PRs.

Add acceptance tests throughout, not only at the end. Constant-table cleanup can
proceed independently; persistence and hot-path changes need proportionate
compatibility and performance validation.

## Module-level mutable dictionaries

Inventory scope: first-party Python runtime files in `lib/` and `dirsearch.py`;
module-level dictionary literals, comprehensions and dictionary constructors.
Tests, third-party internals, per-instance fields and dynamically created aliases
are not counted. Writes were checked separately from the declared types.

No dictionaries in this inventory have identified production writes after the
options migration. `lib/core/data.py` is removed; `default_options()` constructs
new per-invocation containers rather than exposing a mutable module-level value.

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

Neither `dirsearch.py` nor `lib/controller/controller.py` imports global options.
Logging likewise has no global option dependency or process-global handler.

## Other global state and import-time values

This inventory distinguishes mutable state from read-only data; it does not list
every scalar constant, compiled regex, imported module or third-party singleton.

| Name / mechanism | Location | Ownership concern |
| --- | --- | --- |
| `_request_target_state` | `lib/connection/requester.py` | `threading.local()` raw-target context: separate per thread, but still ambient. |
| Signal registrations | `Controller._run_targets()` | Process-wide handlers; installation/restoration needs an explicit owner. |
| Async event-loop policy | `Controller._run_targets()` | Optional uvloop policy selection is still process-wide; explicit lifecycle entry does not isolate it. |
| `TEXT_CHARS` | `lib/core/settings.py` | Mutable `bytearray` used as a read-only binary-detection table; no production writes identified. |
| `__all__` lists | `lib/core/api.py`, `dirsearch.py` | Static export metadata, not run progress. |

Import-time platform/path constants also remain, but are not mutable progress.
Invocation command/date metadata no longer comes from module-level constants.
`_stealth_word_generator` and `rand_stealth_word()` were removed; calibration
generators now use an instance-owned `random.Random`. Other utility calls still
borrow the standard library's default RNG and are outside this ownership step.
Inspected native maps and wordlist indexes are
session/instance-owned, not additional process-global mutable dictionaries;
native task-local contexts likewise are not shared global progress maps.
