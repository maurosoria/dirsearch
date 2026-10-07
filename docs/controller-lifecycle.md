# Explicit controller lifecycle

The CLI now calls `Controller(metadata=metadata).run()`. Construction and
execution are separate; `run()` owns the complete, single-use lifecycle.
This is an internal refactor, not a replacement for the documented
`DirsearchFuzzer` Python API or a new scheduling interface.

## Phase boundaries

| Phase | Responsibility | Side effects |
| --- | --- | --- |
| `__init__` | Capture/inject invocation metadata and borrowed output stream; initialize local state | Reads argv/clock when metadata is omitted; no CLI-option reads, resource opening, preparation, requests or signal installation |
| `run()` bootstrap | Reject a repeated attempt, create terminal/logger and transfer them to `RunResources` | Opens bootstrap output history; closes it if logger construction fails before transfer |
| `_prepare()` | Select existing fresh `setup()` or session `_import()` | Validate input, prepare policies, dictionary, reports and stores at their existing boundaries |
| `_run_targets()` | Existing engine setup and sequential target loop | Existing requester/loop creation, signal registration and execution |
| `run()` final cleanup | Always close attached `RunResources` after preparation/execution | Existing ordered teardown, including downstream cleanup after an earlier failure |

The target-loop body is unchanged apart from its internal method name. Engine
selection, worker draining, deadlines, recursion, report callbacks and session
continuation are not redesigned here. Configuration, persistence input and live
resources retain their separate owners.

## Lifetime and failure contract

Before `run()`, `resources` is explicitly `None`; simply constructing and then
discarding a controller has no live handles to close. Metadata and the output
stream are captured at construction. The transitional global CLI options are
read at execution, not captured by the constructor. Consequently, deferring a
controller does **not** freeze a future invocation's configuration.

The execution attempt is consumed before reading bootstrap options or acquiring
resources. A second `run()` raises `RuntimeError` before starting work, whether
the first attempt succeeded, failed during preparation, was interrupted, or
failed during cleanup. Reentrant execution is rejected too. A failed startup is
not implicitly retryable on the same object; a new invocation needs a new owner.
This check is not a thread-safety guarantee.

Once resources are attached, `run()` closes them in `finally`, including on
`SystemExit` and `KeyboardInterrupt`. Bootstrap logger-construction failure
closes the terminal that has not yet been transferred. The terminal never closes
its borrowed output stream. Resource-specific close ordering, exception chaining
and no-retry semantics remain in [RunResources](run-resources.md). Force-quit
still bypasses ordinary cleanup.

`_prepare()` and `_run_targets()` are internal phases, not alternative public
entrypoints. Callers must not invoke them to bypass the lifecycle owner. There is
no public prepare-and-hold state, manual controller-close API or automatic-run
compatibility flag. Existing internal callers and fixtures move together.

## Limits and verification

The CLI still normalizes options, handles wordlist-only mode and confirms session
resume before entering the controller. Its output, exit behavior and metadata
ordering are preserved. The package entrypoint and standalone script use the
same explicit invocation; the public Python API is unchanged.

Global CLI normalization, signals, async event-loop policy and ambient request
context remain process concerns. This does not enable concurrent controllers,
parallel targets, external scheduling, or independently executable checkpoints.
Those require separate designs and acceptance tests; see the
[refactoring backlog](refactoring-backlog.md).

Run `python -m unittest discover -s tests -t .`. Lifecycle tests cover deferred
construction, fresh/resume ordering, repeated and reentrant execution, partial
startup failures, interruptions, borrowed stream ownership and independent local
resource owners. Existing preparation/resume tests now explicitly call `run()`;
isolated target-loop fixtures call `_run_targets()`. CLI tests assert execution
is invoked, and the existing loopback contracts exercise all three engines.
The installed-package smoke verifies both unstarted and completed resource states.

No new runtime modules, dependencies, CLI flags, checkpoint/report schemas,
request pacing or native chunk defaults are introduced. No performance change
is claimed.
