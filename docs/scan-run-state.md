# Run and target progress ownership

`ScanRunState` in `lib/core/scan_run_state.py` owns target ordering and cumulative
progress for one sequential controller run. `TargetProgress` in
`lib/core/target_progress.py` owns the current target's working data. Both are
explicitly initialized during controller setup or restoration; they contain no
requester, report manager or engine handles.

| State | Owner | Existing lifetime |
| --- | --- | --- |
| Pending inputs and active target | `ScanRunState` | Whole run; active-first session ordering |
| `passed_urls` | `ScanRunState` | Directory URLs already scheduled anywhere in this run, not successfully completed targets |
| `jobs_processed`, `errors`, `consecutive_errors` | `ScanRunState` | Cumulative jobs/errors and the existing cross-job/target error streak |
| `old_session` | `ScanRunState` | Existing resume-presentation flag, cleared after a directory job; it can survive a handled exit before any job starts |
| Prepared origin (`url`) and starting path (`base_path`) | `TargetProgress` | Updated during target preparation |
| Pending/current directories | `TargetProgress` | First entry stays present until its workers drain; completion pops it, handled target errors clear the queue |

The current target is still a sequential working slot. This extraction does not
create independently schedulable tasks, reset deduplication between duplicate
targets, or change error-streak policy. Dictionary claims remain owned by
`Dictionary`; run timing remains controller-owned.

Configuration describes what to run; mutable state describes what remains.
Global `options["urls"]` is now input only: running, skipping and completing
targets do not consume the caller's list. Later changes to that list do not
replace work already copied into the run state.

`Controller.run()` calls `prepare_targets()` after setup or restoration and before
starting workers/installing signal handlers. Preparation replaces only the input
ordering, preserving restored counters, scheduled URLs and presentation state.
It rejects active work, and a failing input iterable leaves the prior state
unchanged. It is not a live scheduling/reconfiguration API.

[TargetConfig](target-configuration.md) separately freezes run-wide target
preparation hints such as the default scheme and explicit connection-host
override. Neither these hints nor parsed target details belong in the queue.

## Pending versus active

The state separates pending targets from one optional active target. An immutable
tuple holds the input URLs; a cursor identifies the pending suffix. URLs retain
their original spelling, order and duplicates; URL parsing and validation still
belong to the controller.

| Operation | Active target | Pending targets | Checkpoint URL list |
| --- | --- | --- | --- |
| Initialize with A, B, C | None | A, B, C | A, B, C |
| `activate_next()` | A | B, C | A, B, C |
| `finish_active()` | None | B, C | B, C |
| `activate_next()` | B | C | B, C |

Activating while a target is already active raises `RuntimeError`, even if the
pending suffix is empty. Finishing with no active target is also an error.
Activating an exhausted run returns `None`; an empty string is still an input
target, not the exhaustion sentinel.

Each transition publishes the input tuple, cursor and active target together in one immutable
position object. This matters even in sequential execution: a Ctrl+C handler can
save between Python instructions. Removing a pending entry and then assigning the
active target separately would briefly omit it from a checkpoint. Snapshots read
one position, so they see either side of the transition, not a partially moved
target. This is not a replacement for synchronization between multiple consumers.

`finish_active()` ends an attempt, not necessarily a successful scan. The
controller retains its existing target-exit handling: success, skipped/invalid
targets and exceptions leaving the target's `try` block finish that attempt.
A fuzzer-construction failure occurs before that block, so the active target is
retained and no later target starts. There is no new automatic retry policy.

Progress uses `pending_count` for future targets, `TargetProgress.directories`
for current work and `ScanRunState.jobs_processed` for completed jobs. The pause menu
offers skip only when another target is pending. Neither path reads the global
URL list. Queue activation and pending counts are constant-time operations; a
full list is copied only for a checkpoint snapshot.

## Sessions

`snapshot_targets()` returns a detached list containing the active target first,
followed by pending targets. Saving overlays this list on prepared options in a
[SessionSnapshot](session-snapshots.md), after flushing reports. It does not temporarily overwrite
global options or consume queue entries, including if saving fails.

Quit-and-save writes the checkpoint **before** unwinding the active attempt.
Completed targets are absent; the interrupted target remains first. Resume
reconstructs the queue from this list and restores the dictionary and directory
progress through the existing session code. The version-1 JSON schema is
unchanged: no cursor, state object or engine-specific queue is serialized.
`Controller._snapshot_session()` captures `RunCheckpoint` and `TaskCheckpoint`
values; `SessionStore` maps them to the same flat `controller` JSON fields.
Restoration reconstructs their owned containers; there
are no compatibility properties or dynamic fallbacks for the former flat
controller attributes.

## Scope and limits

All three engines use the same controller-owned state. Target execution remains
sequential; request concurrency within a target is unchanged. Only the controller
performs queue transitions. Existing callbacks update cumulative counters and
directory progress with their existing synchronization; neither state object is
a thread-safe multi-consumer queue. No new per-request state object, callback,
lock or Python/Rust crossing is introduced. No throughput gain is claimed.

This refactor does not introduce scheduling policy, remote workers or a GUI API,
and does not make complete controllers safe to run concurrently. Requesters,
dictionary progress and output resources still need task-level lifecycle
boundaries before independent tasks can execute concurrently. A public task
descriptor remains future work. `TaskCheckpoint` now records the current slot's
data, but cannot execute independently of the enclosing session. Rust's internal
`ScanTask` and its Python interface are unchanged.

## Validation

Run `python -m unittest discover -s tests -t .`.

Tests cover transitions and invalid transitions, checkpoints between preparation/activation
instructions, detached inputs/snapshots, duplicates and raw URL spelling,
independent state instances, preservation of restored totals, progress and pause
behavior with contradictory global options, handled target exits, startup
failure, checkpoint writes and failures, and resume across the three engines.
Existing worker-drain, wordlist-resume and loopback CLI contracts remain in use.
The new controller characterization exercises repeated targets, cumulative
counters and directory deduplication with controlled fuzzer lifecycles across
all three engine selectors; it is not a multi-controller concurrency test.

The installed-package smoke imports and exercises both state owners. Setuptools
discovers it under `lib.core`; PyInstaller's existing `collect_submodules('lib')`
includes it without a new hidden-import list.
