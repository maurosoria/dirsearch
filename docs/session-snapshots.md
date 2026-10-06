# Session persistence boundary

Session persistence remains Python-owned and engine-independent. `SessionStore`
reads, validates and writes the existing version-1 JSON representation; it does
not read a live controller, retain run options, construct dictionaries/reporters,
or mutate the caller's output history.

The controller now composes its progress from `ScanRunState` (queue and run-wide
totals) and `TargetProgress` (origin, starting path and directories). Snapshot
capture now builds typed run/task checkpoints. Storage exports the same flat
JSON fields; no state class or engine handle is serialized.

## Ownership and ordering

| Stage | Owner | Contract |
| --- | --- | --- |
| Preparation | Controller | Copy normalized options after raw-request setup or validated session restore. |
| Save preparation | Controller | Flush report rows, capture active/pending `TaskSpec` entries from `ScanRunState`, and capture dictionary progress including outstanding claims. |
| Snapshot | `SessionSnapshot` | Group `remaining_tasks`, immutable run/task checkpoints, detached normalized options and output history. |
| Persistence | `SessionStore.save(snapshot, path)` | Encode options and atomically replace the existing JSON checkpoint. |
| Commit history | Controller | Adopt the snapshot's history only after a successful save. |
| Load | `SessionStore.load(path)` | Validate JSON, decode normalized option types and apply historical defaults into a `SessionSnapshot`; no live resources. |
| Resume | Controller | Validate option policy, rebuild owned state/dictionary/report manager from typed values and retain normal resource cleanup ownership. |

`SessionSnapshot` describes the current sequential run. Its progress is divided
by ownership rather than the historical JSON layout:

| Value | Contents | Scope |
| --- | --- | --- |
| `TaskSpec` | Exact original target text, including path, query and credentials | One ordered input entry, not a prepared origin or globally unique ID |
| `RunCheckpoint` | Start time, scheduled directory URLs, job/error totals and resume-presentation flag | Cumulative run state |
| `TaskCheckpoint` | Prepared origin, starting path, ordered directory queue and dictionary checkpoint | Current sequential target slot |
| `DictionaryCheckpoint` | Complete corpus, dynamic paths and their resumable cursors | Current directory job; later jobs reset the cursors |

These frozen values copy sequence inputs into tuples, preserving order, spelling
and duplicates. `DictionaryCheckpoint.to_state()` allocates fresh lists for each
restored dictionary. Reusing one snapshot to reconstruct two owners cannot share
their mutable progress. The old internal `controller`/`dictionary` mappings are
removed; there are no dictionary-shaped compatibility fallbacks.

Options and output history remain detached mutable data. The enclosing snapshot
is therefore not deeply immutable or a thread-safe capture algorithm. Capture
still uses the existing paused save boundary. Callers must not mutate a snapshot
while another operation serializes it.

The constructors copy input containers; changing live headers, targets,
directory lists or output entries afterward cannot alter the pending write.
Conversely, manipulating the snapshot cannot mutate the source controller.
Its representation excludes all payload fields, which may contain credentials
or captured terminal text. The checkpoint itself still contains the data needed
for resume and uses the existing private-file permissions.

`SessionSnapshot.remaining_tasks` is an immutable, active-first tuple of
`TaskSpec` entries. `task_checkpoint` is the continuation for the first entry;
later entries use reset dictionary cursors. The original target is not derived
from `TaskCheckpoint.url`: for example, a target with credentials, path and query
may share its prepared origin with many different inputs. Duplicate specs stay
as separate positions; equality of descriptors does not identify one execution.

Target input no longer belongs in the snapshot's `options` mapping. Construction
rejects a second `urls` input there. Only the storage adapter writes
`[task.target for task in snapshot.remaining_tasks]` into the legacy
`options.urls` JSON field. Load extracts that field into descriptors and removes
it from the returned options. Missing/null legacy URL lists produce no tasks;
they are never reconstructed from a prepared origin or unrelated CLI targets.
Controller import projects those descriptors into the existing CLI composition
boundary, which remains transitional.

`TaskSpec` and `TaskCheckpoint` are not independently runnable or portable: the
enclosing run's policy and deduplication are still needed. The current slot can
be empty before preparation or retain the previous origin during a transition;
an empty directory queue does not prove successful completion. Independent
contexts, stable execution IDs and explicit resource lifecycle remain future
work. Rust's internal `ScanTask` is unrelated and unchanged.

The controller's `_session_options` is a transitional, detached copy of normalized
input. Export no longer rereads process-global options. It is not yet the planned
aggregate of prepared component policies: setup, restore and engine composition
still use the CLI options boundary. Complete controllers are not yet safe to run
concurrently in one process.

## Compatibility and cost

- JSON field names, schema version, bytes encoding, active-first target ordering,
  wordlist claims and cross-engine resume are unchanged.
- `load()` now returns a `SessionSnapshot`, with bytes, sets and tuples already
  decoded in its options. Runtime reconstruction is explicit in
  `Controller._restore_session()`; loading alone opens no runtime resources.
- Historical defaults for absent optional progress fields stay in storage.
  Missing/invalid `start_time` and explicit null progress are rejected by both
  load and listing instead of reaching runtime restoration with invalid types.
  This is structural validation, not complete validation of every option value;
  controller composition still validates numeric/regex/header policy.
- Existing checkpoint-file paths and the four-file JSON migration bridge remain
  supported. The documented future removal of that bridge is unchanged.
- Output history is initialized explicitly. Resume imports prior output; a fresh
  run does not borrow history from an unrelated existing destination. The old
  missing-attribute/destination-history fallback is removed.
- Copies happen during preparation, capture and restoration, not per request or
  native chunk. A checkpoint still materializes the saved wordlist; this is not
  an incremental checkpoint implementation or a throughput improvement claim.
- One small descriptor is allocated per input target at preparation/load.
  Capturing the remaining queue copies references to immutable descriptors;
  target strings are neither parsed nor deep-copied at that boundary.
- Report flushing, atomic replacement and durability ordering are unchanged.

## Validation

Run `python -m unittest discover -s tests -t .`. Focused coverage is in
`tests.controller.test_session_snapshot`, `tests.controller.test_session_store`
and `tests.controller.test_scan_run_state`; descriptor/queue contracts are in
`tests.core.test_task_spec` and `tests.core.test_scan_run_state`.

Coverage includes immutable target input/progress, duplicate queue positions,
raw target versus prepared origin, repeated independent restores, typed load,
invalid/null progress, historical defaults, detached nested inputs, exact JSON
structure, repeated snapshot writes, resource-free storage, prepared options after fresh setup and resume for
all three engine selectors, failed writes/replaces, history commit/retry, legacy
output history, cross-engine progress, file permissions and legacy migration.
An additional extension-backed test round-trips a partially released native
wordlist claim through JSON and checks remaining work plus the full reset corpus.
Engine-selection tests use controlled controller lifecycles; existing native
integration and loopback tests separately exercise the real backends.

`tests/check_packaged_install.py` exercises an installed snapshot round trip.
It also verifies that loading returns the same checkpoint classes under the
installed package namespace. Checkpoint imports are package-relative so source
and installed entrypoints do not mix `lib` and `dirsearch.lib` value classes.
Setuptools discovers the modules under `lib.controller` and `lib.core`,
PyInstaller collects `lib` submodules, and the existing CI package smoke executes
that check. No new dependency, Rust ABI change or bundling rule is needed.
