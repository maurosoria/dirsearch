# Target progress ownership

`ScanRunState` in `lib/core/scan_run_state.py` owns the target progress of one
sequential controller run. `Controller.run()` creates it after raw-request setup
or session restoration, before constructing requesters or starting work.

Configuration describes what to run; mutable state describes what remains.
Global `options["urls"]` is now input only: running, skipping and completing
targets do not consume the caller's list. Later changes to that list do not
replace work already copied into the run state.

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

Each transition publishes the cursor and active target together in one immutable
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

Progress uses `pending_count` for future targets, while current directories and
completed jobs keep their existing controller-owned counters. The pause menu
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

## Scope and limits

All three engines use the same controller-owned state. Target execution remains
sequential; request concurrency within a target is unchanged. Only the controller
performs state transitions. This class is not a thread-safe multi-consumer queue.

This refactor does not introduce scheduling policy, remote workers or a GUI API,
and does not make complete controllers safe to run concurrently. Requesters,
dictionary progress, discovery directories and terminal/output state still need
their own lifetime and ownership boundaries. Rust's internal `ScanTask` and its
Python interface are unchanged.

## Validation

Run `python -m unittest discover -s tests -t .`.

Tests cover transitions and invalid transitions, checkpoints between activation
instructions, detached inputs/snapshots, duplicates and raw URL spelling,
independent state instances, progress and pause
behavior with contradictory global options, handled target exits, startup
failure, checkpoint writes and failures, and resume across the three engines.
Existing worker-drain, wordlist-resume and loopback CLI contracts remain in use.

The installed-package smoke imports and exercises `ScanRunState`. Setuptools
discovers it under `lib.core`; PyInstaller's existing `collect_submodules('lib')`
includes it without a new hidden-import list.
